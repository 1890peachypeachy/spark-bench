# 2026-09-02 10:27:39 by RouterOS 7.24.2
# software id = 63WI-1DTC
#
# model = CRS804-4DDQ
# serial number = HN90BS1PW7K
/interface bridge
add admin-mac=38:32:7A:94:C4:5F auto-mac=no comment=defconf name=bridge
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

