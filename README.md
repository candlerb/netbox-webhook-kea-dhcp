# Netbox kea-dhcp updater

This code reads in KEA DHCP configs (`/etc/kea/kea-dhcp[46].conf`),
updates them to include statically-assigned MAC to IP assignments from
Netbox, and writes them out again as `/var/lib/kea/kea-dhcp[46].conf`

If the config has changed, it then signals the server to reload its config
from disk.

*But can't KEA read host reservations directly from Postgres?*

[Yes](https://kea.readthedocs.io/en/v1_6_0/arm/admin.html#postgresql) - it
might be possible to make a read-only view on the Netbox tables that looks
like the tables KEA expects to find.

However you'd then have to replicate your Netbox database if you want a
[high-availability](https://kea.readthedocs.io/en/v1_6_0/arm/hooks.html#ha-high-availability)
configuration.

In any case, other configuration items such as subnets and pools currently
cannot come from Postgres - only from the config file, or a
[mysql](https://kea.readthedocs.io/en/v1_6_0/arm/config.html#cb-components)
configuration backend.

*So does this code also add subnet and pool definitions from Netbox?*

No, at least not yet.  Subnets and pools must be added by hand into
`/etc/kea/kea-dhcp[46].conf`.

Netbox doesn't yet have a concept of [ranges](https://github.com/netbox-community/netbox/issues/834)
to define pools which would be helpful - although it would be possible
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
isc-kea-dhc4-server` and entering the following (capitalisation needs to be
exactly right):

```
[Service]
ExecStart=
ExecStart=/usr/sbin/kea-dhcp4 -c /var/lib/kea/kea-dhcp4.conf
Restart=On-Failure
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
