# /bin/ifconfig — estado de la red.  ifconfig | ifconfig dhcp | ifconfig IP/PREF,PUERTA,DNS
def main(argv):
    if len(argv) > 1:
        spec = argv[1]
        try:
            net_config(spec)
        except OSError as e:
            print("ifconfig: %s" % e)
            return 1
        if spec == "dhcp":
            print("ifconfig: pidiendo dirección por DHCP...")
            for _ in range(100):
                if net_info().get("configured"):
                    break
                sleep_ms(100)
    i = net_info()
    print("lo:   inet 127.0.0.1  (bucle local)")
    if not i.get("nic", True):
        print("net0: no hay red: %s" % i.get("reason", "?"))
        return 1
    print("net0: %s" % i["driver"])
    print("      ether %s   enlace %s" % (i["mac"], "activo" if i["link"] else "CAÍDO"))
    if i["configured"]:
        print("      inet %s  máscara %s   (%s)" % (i["ip"], i["mask"], i["method"]))
        print("      puerta %s   dns %s" % (i["gw"], i["dns"]))
    else:
        print("      sin dirección (DHCP: %s)" % i["dhcp"])
    st = i["stats"]
    print("      RX %d tramas (%d bytes)   TX %d tramas (%d bytes)   descartadas %d"
          % (st["rx"], st["rx_bytes"], st["tx"], st["tx_bytes"], st["drop"]))
    return 0
