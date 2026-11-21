import time

import pytest

from pyos.hal.emulated import FileDisk as DiskController
from pyos.kernel.errors import KError, EEXIST, EINVAL, ENOENT, ENOTEMPTY, EFBIG
from pyos.kernel.fs.buffercache import BufferCache
from pyos.kernel.fs.pyfs import BLOCK, MAX_FILE, PyFS
from pyos.kernel.fs.vfs import O_CREAT, O_RDONLY, O_RDWR, O_TRUNC, OpenFile

NBLOCKS = 1024  # 4 MiB


@pytest.fixture
def disk(tmp_path):
    p = tmp_path / "fs.img"
    p.write_bytes(bytes(NBLOCKS * BLOCK))
    d = DiskController(str(p))
    PyFS.format(BufferCache(d, 0, BLOCK, NBLOCKS), time.time, inode_count=256)
    yield d
    d.close()


def mount(disk, capacity=512):
    return PyFS(BufferCache(disk, 0, BLOCK, NBLOCKS, capacity=capacity), time.time)


def wr(fs, path, data):
    of = OpenFile(fs.open(path.strip("/").split("/"), O_RDWR | O_CREAT | O_TRUNC), O_RDWR, path)
    of.write(data)
    of.close()


def rd(fs, path):
    of = OpenFile(fs.open(path.strip("/").split("/"), O_RDONLY), O_RDONLY, path)
    out = b""
    while chunk := of.read(65536):
        out += chunk
    of.close()
    return out


def test_crear_leer_y_persistir(disk):
    fs = mount(disk)
    fs.mkdir(["etc"])
    wr(fs, "/etc/hola", b"mundo")
    fs.unmount()
    fs2 = mount(disk)
    assert fs2.was_clean
    assert rd(fs2, "/etc/hola") == b"mundo"
    assert fs2.readdir(["etc"]) == [("hola", "file")]


def test_fichero_grande_bloque_indirecto_y_liberacion(disk):
    fs = mount(disk, capacity=8)  # caché diminuta: fuerza expulsiones write-back
    free0 = fs.sb["free_blocks"]
    data = bytes(range(256)) * (3 * 1024 * 1024 // 256)  # 3 MiB > 12 bloques directos
    wr(fs, "/big", data)
    assert rd(fs, "/big") == data
    fs.unlink(["big"])
    assert fs.sb["free_blocks"] == free0
    with pytest.raises(KError) as e:
        fs.write(fs._create(["huge"], 1), MAX_FILE, b"x")
    assert e.value.errno == EFBIG


def test_ficheros_dispersos_y_truncado(disk):
    fs = mount(disk)
    ino = fs._create(["s"], 1)
    fs.write(ino, 3 * BLOCK, b"fin")
    assert fs.read(ino, 0, 4) == b"\0" * 4
    assert fs.iget(ino).size == 3 * BLOCK + 3
    fs.write(ino, 0, b"ABCDEFGH")
    fs.truncate(ino, 2)
    fs.write(ino, 6, b"Z")
    assert fs.read(ino, 0, 7) == b"AB\0\0\0\0Z"  # la cola truncada no reaparece


def test_errores_de_directorio(disk):
    fs = mount(disk)
    fs.mkdir(["d"])
    wr(fs, "/d/f", b"x")
    with pytest.raises(KError) as e:
        fs.rmdir(["d"])
    assert e.value.errno == ENOTEMPTY
    with pytest.raises(KError) as e:
        fs.mkdir(["d"])
    assert e.value.errno == EEXIST
    with pytest.raises(KError) as e:
        fs.open(["nada"], O_RDONLY)
    assert e.value.errno == ENOENT
    with pytest.raises(KError) as e:
        fs.rename(["d"], ["d", "sub"])
    assert e.value.errno == EINVAL


def test_rename_de_directorio_actualiza_enlaces(disk):
    fs = mount(disk)
    fs.mkdir(["a"])
    fs.mkdir(["b"])
    fs.mkdir(["a", "x"])
    fs.rename(["a", "x"], ["b", "x"])
    assert fs.stat(["a"])["links"] == 2 and fs.stat(["b"])["links"] == 3
    assert fs.fsck(repair=False)["errors"] == 0


def test_unlink_con_fichero_abierto(disk):
    fs = mount(disk)
    wr(fs, "/tmp", b"sigue-vivo")
    free0 = fs.sb["free_blocks"]
    of = OpenFile(fs.open(["tmp"], O_RDONLY), O_RDONLY, "/tmp")
    fs.unlink(["tmp"])
    assert of.read(100) == b"sigue-vivo"  # semántica POSIX: el inodo vive hasta el close
    of.close()
    assert fs.sb["free_blocks"] == free0 + 1


def test_fsck_repara_y_detecta_montaje_sucio(disk):
    fs = mount(disk)
    wr(fs, "/f", b"datos")
    fs.sync()                 # sin unmount -> queda "sucio"
    fs._bit_set(fs.sb["bbmap_start"], fs.sb["total_blocks"] - 1, 1)  # bloque fugado
    fs.sync()
    fs2 = mount(disk)
    assert not fs2.was_clean
    report = fs2.fsck(repair=True)
    assert report["block_bitmap"] >= 1
    assert fs2.fsck(repair=False)["errors"] == 0
    assert rd(fs2, "/f") == b"datos"
