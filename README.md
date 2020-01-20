# Netbox kea-dhcp updater

This code reads in KEA DHCP configs (`/etc/kea/kea-dhcp[46].conf`),
updates them to include statically-assigned MAC to IP reservations from
Netbox, and writes them out again as `/var/lib/kea/kea-dhcp[46].conf`

If the config has changed, it then signals the server to reload its config
from disk.

Example input:

```
  ...
  "subnet4": [
    {
      "subnet": "192.168.1.0/24",
      "pools": [
        { "pool": "192.168.1.100 - 192.168.1.149", "client-class": "HA_dhcp1" },
        { "pool": "192.168.1.150 - 192.168.1.199", "client-class": "HA_dhcp2" }
      ],
      "option-data": [
        { "name": "routers", "data": "192.168.1.1"}
      ]
    }
  ]
```

Example output:

```
    ...
    "subnet4": [
      {
        "subnet": "192.168.1.0/24",
        "pools": [
          {
            "pool": "192.168.1.100 - 192.168.1.149",
            "client-class": "HA_dhcp1"
          },
          {
            "pool": "192.168.1.150 - 192.168.1.199",
            "client-class": "HA_dhcp2"
          }
        ],
        "option-data": [
          {
            "name": "routers",
            "data": "192.168.1.1"
          }
        ],
        "reservations": [
          {
            "hw-address": "bb:bb:bb:bb:bb",
            "ip-address": "192.168.1.33",
            "hostname": "prometheus.example.net."
          },
          {
            "hw-address": "cc:cc:cc:cc:cc:cc",
            "ip-address": "192.168.1.253",
            "hostname": "ap-front.example.net."
          },
          {
            "hw-address": "aa:aa:aa:aa:aa:aa",
            "ip-address": "192.168.1.3",
            "hostname": "storage1.example.net."
          },
          {
            "hw-address": "dd:dd:dd:dd:dd:dd",
            "ip-address": "192.168.1.254",
            "hostname": "ap-rear.example.net."
          }
        ],
        "id": 2
      }
    ]
```

**Is it a Netbox webhook?**

No, it's not actually a webhook (yet).  It's a script than you can run from
cron, or run manually when you've changed IP assignments.

If it were to be triggered as a webhook, it would have to be triggered on
all Device, Interface and IPAddress changes - but since the messages
[don't say which fields have changed](https://github.com/netbox-community/netbox/issues/3451),
we would have to do a full DHCP rebuild on every such change.

A future compromise would be a webhook which sets a flag to schedule a
rebuild to be done in the next minute (say).

**But can't KEA read host reservations directly from Postgres?**

[Yes](https://kea.readthedocs.io/en/v1_6_0/arm/admin.html#postgresql) - it
might be possible to make a read-only view on the Netbox tables that looks
like the tables KEA expects to find.

However you'd then have to replicate your Netbox database if you want a
[high-availability](https://kea.readthedocs.io/en/v1_6_0/arm/hooks.html#ha-high-availability)
DHCP configuration.

In any case, other configuration items such as subnets and pools currently
cannot come from Postgres - only from the config file, or a
[mysql](https://kea.readthedocs.io/en/v1_6_0/arm/config.html#cb-components)
configuration backend.

**So does this code also add subnet and pool definitions from Netbox?**

No, at least not yet.  Subnets and pools must be added by hand into
`/etc/kea/kea-dhcp[46].conf`.

Netbox doesn't yet have a concept of [ranges](https://github.com/netbox-community/netbox/issues/834)
to define pools, which would be helpful - although it would be possible
to define Custom Fields on the Prefix object.

## Logic

The existing configuration is read in, and some postgres queries run.  Any
static assignments in the Netbox database are added under the relevant
subnets.

A static assignment is where:

* the device or VM has an interface with a MAC address; *and*
* it has a primary IP4 and/or primary IP6 address on that interface

Additionally, if the IP address has a `dns_name` assigned, this is also
included in the DHCP static assignment.

Currently, only the primary IPv4/IPv6 addresses are configured for DHCP.
(Otherwise, if an interface had multiple IPv4 addresses, it wouldn't know
which one to return; although multiple addresses can be returned for IPv6)

The code finds the Netbox Prefix for the IP address.  If there is no
matching subnet4/6 in the KEA configuration, then one is not created.

The "id" added to the subnet is the netbox id of the Prefix object.
If there is an existing id, is it retained instead.

## Dependencies

```
apt-get install python3-psycopg2
```

## Configuration

### Enable remote access to database

This code makes direct Postgres queries, since the Netbox API can't do
joins.

Create a new database user for doing the queries:

```
create user dhcp with password 'XXX';
grant select on virtualization_virtualmachine,dcim_device,dcim_interface,ipam_ipaddress,ipam_prefix to dhcp;
```

Enable remote connections in `postgresql.conf`:

```
listen_addresses = '*'
```

And edit `pg_hba.conf` to allow connections from the DHCP server(s):

```
host    netbox          dhcp            192.0.2.1                md5
```

### Python code

Insert the database server hostname/IP address, and the user/password you
have created, in the python code.

Run the python script, and it should create `/var/lib/kea/kea-dhcp[46].conf`

Inspect it to check it looks valid.

### KEA

Override the KEA config startup scripts so that it reads the freshly-written
configs in the new location, by running `systemctl edit
isc-kea-dhcp4-server` and entering the following (capitalisation needs to be
exactly right):

```
[Service]
ExecStart=
ExecStart=/usr/sbin/kea-dhcp4 -c /var/lib/kea/kea-dhcp4.conf
Restart=on-failure
RestartSec=5
```

Repeat for dhcp6.

Note that the service is called `isc-kea-dhcp[46]-server` if installed from
[cloudsmith.io](https://cloudsmith.io/~isc/repos/kea-1-6/setup/#formats-deb)
packages, or `kea-dhcp[46]-server` if installed from Ubuntu standard
repos (which have an older version)

## Licence

This work is licensed under the same terms as Netbox itself, which is Apache
2.0.

It Works For Me™, but you should be prepared to hack python code if it
doesn't work for you.
