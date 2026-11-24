"""Almacén de claves de UC (SPEC_UC §5.5): de las anclas incluidas (raíz y recuperación) y la
cadena de registros UCKEYREC firmados, deduce qué claves pueden firmar qué canales.

Lo usan el kernel (update_keyrec, update_begin) y el bootloader (que verifica él mismo el
almacén desde la raíz incluida, UC-36). Solo depende de crypto.manifest y crypto.ed25519.
"""
from ..crypto import ed25519
from ..crypto.manifest import ManifestError, parse_keyrec, parse_sig

MAX_CHAIN = 28            # lo que cabe en una copia del almacén (31 sectores)


class Keyring(object):
    def __init__(self, root, recovery):
        self.root = root                  # (key_id, pubkey bytes) o None
        self.recovery = recovery
        self.keys = {}                    # key_id -> {"pubkey", "channels", "role"}
        self.revoked = set()
        self.retired = {}                 # claves revocadas: solo para ARRANCAR lo ya instalado
        self.seq = 0

    def manifest_keys(self):
        """Lo que espera crypto.manifest.verify_manifest."""
        return dict((k, {"pubkey": v["pubkey"], "channels": list(v["channels"])})
                    for k, v in self.keys.items())

    def boot_keys(self):
        """Claves con las que el bootloader acepta un manifiesto YA INSTALADO: las vigentes y
        las revocadas. Revocar una clave impide instalar nada nuevo firmado con ella (el kernel
        usa manifest_keys), pero no deja sin arranque al sistema que se instaló con ella: si no,
        revocar la clave de la versión en uso dejaría la máquina sin un conjunto arrancable si
        la versión nueva falla. Escribir el disco desde fuera de PyOS queda fuera del modelo."""
        out = dict((k, {"pubkey": v["pubkey"], "channels": list(v["channels"])})
                   for k, v in self.retired.items())
        out.update(self.manifest_keys())
        return out

    def describe(self):
        return {"root": self.root[0] if self.root else None,
                "recovery": self.recovery[0] if self.recovery else None,
                "seq": self.seq,
                "keys": dict((k, {"role": v["role"], "channels": list(v["channels"]),
                                  "pubkey": v["pubkey"].hex()})
                             for k, v in sorted(self.keys.items())),
                "revoked": sorted(self.revoked)}

    def apply(self, rec_bytes, sig_bytes):
        """Verifica un registro y lo aplica. ManifestError con el motivo si no vale."""
        rec = parse_keyrec(rec_bytes)
        key_id, sig = parse_sig(sig_bytes)
        if key_id != rec["signed_by"]:
            raise ManifestError("la firma es de %s y el registro dice signed_by %s"
                                % (key_id, rec["signed_by"]))
        if rec["seq"] <= self.seq:                                     # UC-36
            raise ManifestError("seq %d repetido o antiguo (el almacén va por %d)"
                                % (rec["seq"], self.seq))
        act = rec["action"]
        if act in ("add", "revoke"):                                    # UC-28, UC-29
            signer = self.root
            if signer is None or rec["signed_by"] != signer[0]:
                raise ManifestError("'%s' tiene que firmarlo la clave raíz" % act)
        else:                                                           # replace-root, UC-35
            signer = self.recovery
            if signer is None or rec["signed_by"] != signer[0]:
                raise ManifestError("'replace-root' tiene que firmarlo la clave de recuperación")
        if not ed25519.verify(signer[1], rec_bytes, sig):
            raise ManifestError("firma del registro de claves no válida")
        kid = rec["key_id"]
        if act == "add":
            if rec["role"] not in ("release", "sandbox"):
                raise ManifestError("'add' solo admite claves de firma (release o sandbox)")
            if kid in self.keys or kid in self.revoked or (self.root and kid == self.root[0]) \
                    or (self.recovery and kid == self.recovery[0]):
                raise ManifestError("la clave %s ya existe o fue revocada" % kid)
            if not rec["channels"]:
                raise ManifestError("una clave de firma necesita al menos un canal")
            if rec["role"] == "sandbox" and rec["channels"] != ["sandbox"]:
                raise ManifestError("una clave sandbox solo puede firmar el canal sandbox")
            if rec["role"] == "release" and "sandbox" in rec["channels"]:
                raise ManifestError("una clave de releases no puede firmar el canal sandbox")
            self.keys[kid] = {"pubkey": rec["pubkey"], "channels": tuple(rec["channels"]),
                              "role": rec["role"]}
        elif act == "revoke":
            if kid not in self.keys:
                raise ManifestError("la clave %s no está en el almacén" % kid)
            self.retired[kid] = self.keys.pop(kid)
            self.revoked.add(kid)
        else:
            if rec["role"] != "root":
                raise ManifestError("'replace-root' necesita role: root")
            self.root = (kid, rec["pubkey"])
        self.seq = rec["seq"]
        return rec


def replay(chain, root, recovery):
    """Keyring desde las anclas y la cadena guardada. Un registro que no verifica corta la
    cadena ahí (lo siguiente no se aplica) y se informa en `errors`."""
    kr = Keyring(root, recovery)
    errors = []
    for i, (rec, sig) in enumerate(chain[:MAX_CHAIN]):
        try:
            kr.apply(rec, sig)
        except ManifestError as e:
            errors.append("registro %d: %s" % (i + 1, e))
            break
    return kr, errors


def anchors_from_module(mod):
    def one(v):
        if not v:
            return None
        kid, hexkey = v
        return (kid, bytes.fromhex(hexkey))
    return one(getattr(mod, "ROOT", None)), one(getattr(mod, "RECOVERY", None))
