# 2026-09-02 10:27:39 by RouterOS 7.24.2
# software id = <redacted>
#
# model = CRS804-4DDQ
# serial number = <redacted>
/interface bridge
add admin-mac=<redacted> auto-mac=no comment=defconf name=bridge
/interface bridge port
add bridge=bridge comment=defconf interface=ether1
add bridge=bridge comment=defconf interface=ether2
/interface ethernet switch
set switch1 qos-hw-offloading=yes
/ip address
add address=192.168.88.1/24 comment=defconf interface=bridge network=\
    192.168.88.0
/system routerboard settings
set enter-setup-on=delete-key etherboot-port=ether1

