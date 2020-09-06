#!/usr/bin/python3
import json
import os
import psycopg2
import re
import socket
import subprocess
import sys

DB_CONNECT = "host=netbox.example.net user=dhcp password=XXDBPASSXX dbname=netbox"

SUBNET_QUERY = """SELECT id,prefix
FROM ipam_prefix
WHERE status='active'"""

VM_QUERY = """SELECT DISTINCT vm.name,intf.mac_address,ip.address,ip.dns_name,prefix
FROM virtualization_virtualmachine vm
JOIN virtualization_vminterface intf ON vm.id=intf.virtual_machine_id
JOIN ipam_ipaddress ip ON (vm.primary_ip4_id=ip.id OR vm.primary_ip6_id=ip.id)
                       AND ip.assigned_object_id=intf.id
                       AND ip.assigned_object_type_id=(select id from django_content_type where app_label='virtualization' and model='vminterface')
JOIN ipam_prefix pr ON set_masklen(ip.address,CASE family(ip.address) WHEN 4 THEN 32 ELSE 128 END) << pr.prefix
WHERE pr.status='active' AND mac_address IS NOT NULL"""

DEVICE_QUERY = """SELECT DISTINCT device.name,intf.mac_address,ip.address,ip.dns_name,prefix
FROM dcim_device device
JOIN dcim_interface intf ON device.id=intf.device_id
JOIN ipam_ipaddress ip ON (device.primary_ip4_id=ip.id OR device.primary_ip6_id=ip.id)
                       AND ip.assigned_object_id=intf.id
                       AND ip.assigned_object_type_id=(select id from django_content_type where app_label='dcim' and model='interface')
JOIN ipam_prefix pr ON set_masklen(ip.address,CASE family(ip.address) WHEN 4 THEN 32 ELSE 128 END) << pr.prefix
WHERE pr.status='active' AND mac_address IS NOT NULL"""

def read_confs():
    def rd(filename):
        with open(filename) as f:
            data = f.read()
        lines = data.splitlines()
        lines = [l for l in lines if not re.match(r'^ *(#|//)', l)]
        data = "\n".join(lines)
        #data = re.sub(r',( *\n *[}\]])', r'\1', data)  # allow trailing commas
        return json.loads(data)
    return {
        "4": rd("/etc/kea/kea-dhcp4.conf"),
        "6": rd("/etc/kea/kea-dhcp6.conf"),
    }

def kea_ctrl(dhcp_conf, **kwargs):
    if "control-socket" in dhcp_conf and dhcp_conf["control-socket"]["socket-type"] == "unix":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(dhcp_conf["control-socket"]["socket-name"])
            sock.sendall(json.dumps(kwargs).encode("UTF-8"))
            return json.loads(sock.recv(1_000_000))
        except FileNotFoundError:  # daemon not running
            return None
        finally:
            sock.close()

def kea_reload(dhcp_conf):
    kea_ctrl(dhcp_conf, command="config-reload")
    #subprocess.run(["systemctl","restart","isc-kea-dhcp%s-server" % family])

def write_confs(confs):
    def wr(confs, family, dest):
        conf = confs[family]
        a = json.dumps(conf, indent=2)
        try:
            with open(dest) as f:
                b = f.read()
                if a == b:
                    print("No changes to %s" % dest, file=sys.stderr)
                    return
        except FileNotFoundError:
            pass
        with open(dest+".new", "w") as f:
            f.write(a)
        # TODO: newer versions of kea-dhcp support -t <file> to test config
        os.rename(dest+".new", dest)
        kea_reload(conf["Dhcp%s" % family])
    wr(confs, "4", "/var/lib/kea/kea-dhcp4.conf")
    wr(confs, "6", "/var/lib/kea/kea-dhcp6.conf")

def update_confs(conn, confs):
    subnets = {}  # quick lookup prefix=>info
    for r in confs["4"]["Dhcp4"]["subnet4"] + confs["6"]["Dhcp6"]["subnet6"]:
        if "subnet" in r:
            subnets[r["subnet"]] = r

    def addhosts(cur):
        for shortname, mac, ip, longname, s in cur:
            if s not in subnets:
                continue   # subnets need creating manually for pools, gateway etc
            subnet = subnets[s]
            if ":" in ip:
                info = {"hw-address": mac, "ip-addresses": [re.sub(r'/.*', r'', ip)]}
            else:
                info = {"hw-address": mac, "ip-address": re.sub(r'/.*', r'', ip)}
            if longname:
                name = longname+"."
            else:
                name = shortname
            if name:
                info["hostname"] = name
            subnet.setdefault("reservations", [])
            subnet["reservations"].append(info)

    cur = conn.cursor()
    try:
        cur.execute(VM_QUERY)
        addhosts(cur)

        cur.execute(DEVICE_QUERY)
        addhosts(cur)

        # Apply stable ids to subnets
        cur.execute(SUBNET_QUERY)
        for id, prefix in cur:
            if prefix in subnets:
                subnets[prefix].setdefault("id", id)

        return confs
    finally:
        cur.close()


if __name__ == "__main__":
    # TODO: locking
    conn = psycopg2.connect(DB_CONNECT)
    try:
        confs = read_confs()
        #print(kea_ctrl(confs["4"]["Dhcp4"], command="config-get"))
        update_confs(conn, confs)
        write_confs(confs)
    finally:
        conn.close()
