# 2026-11-27 19:10:12 by RouterOS 7.25.1
# software id = <redacted>
#
# model = CRS804-4DDQ
# serial number = <redacted>
/interface ethernet switch qos priority-flow-control
add name=pfc-tc3 rx=yes traffic-class=3 tx=yes
/interface ethernet switch qos profile
add dscp=26 name=roce traffic-class=3
add dscp=48 name=cnp traffic-class=6
/interface ethernet switch qos port
set qsfp56-dd-1-1 egress-rate-queue3=200000000000 pfc=pfc-tc3 trust-l3=keep
set qsfp56-dd-1-5 egress-rate-queue3=200000000000 pfc=pfc-tc3 trust-l3=keep
set qsfp56-dd-2-1 egress-rate-queue3=200000000000 pfc=pfc-tc3 trust-l3=keep
set qsfp56-dd-2-5 egress-rate-queue3=200000000000 pfc=pfc-tc3 trust-l3=keep
set qsfp56-dd-3-1 egress-rate-queue3=100000000000 pfc=pfc-tc3 trust-l3=keep
set qsfp56-dd-4-1 egress-rate-queue3=100000000000 pfc=pfc-tc3 trust-l3=keep
/interface ethernet switch qos tx-manager queue
set 1 schedule=high-priority-group weight=1
set 3 ecn=yes weight=1
/ip ssh
set host-key-type=rsa known-hosts-validation=no
/ip service
set ftp disabled=yes
set telnet disabled=yes
set api disabled=yes
set api-ssl disabled=yes
/interface bridge
add admin-mac=<redacted> auto-mac=no comment=defconf name=bridge
/interface ethernet
set [ find default-name=qsfp56-dd-1-1 ] l2mtu=9500 mtu=9000
set [ find default-name=qsfp56-dd-1-5 ] l2mtu=9500 mtu=9000
set [ find default-name=qsfp56-dd-2-1 ] l2mtu=9500 mtu=9000
set [ find default-name=qsfp56-dd-2-5 ] l2mtu=9500 mtu=9000
set [ find default-name=qsfp56-dd-3-1 ] l2mtu=9500 mtu=9000
set [ find default-name=qsfp56-dd-4-1 ] l2mtu=9500 mtu=9000
/interface ethernet switch
set switch1 qos-hw-offloading=yes
/ip address
add address=192.168.88.1/24 comment=defconf interface=bridge network=\
    192.168.88.0
/ip dhcp-client
add comment=mgmt interface=bridge name=client1
/system clock
set time-zone-name=America/Los_Angeles
/system routerboard settings
set enter-setup-on=delete-key etherboot-port=ether1
/interface bridge port
add bridge=bridge comment=defconf interface=ether1
add bridge=bridge comment=defconf interface=ether2
add bridge=bridge interface=qsfp56-dd-1-1
add bridge=bridge interface=qsfp56-dd-2-1
add bridge=bridge interface=qsfp56-dd-3-1
add bridge=bridge interface=qsfp56-dd-4-1
add bridge=bridge interface=qsfp56-dd-1-5
add bridge=bridge interface=qsfp56-dd-2-5
