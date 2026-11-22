#!/bin/bash
# Read-only RoCE/NIC audit for one Spark. No sudo, no writes.
echo "host: $(hostname)  product: $(cat /sys/class/dmi/id/product_name 2>/dev/null)  bios: $(cat /sys/class/dmi/id/bios_version 2>/dev/null)"
echo "kernel: $(uname -r)  driver: $(ethtool -i enp1s0f1np1 2>/dev/null | awk -F': ' '/^driver|^version|^firmware-version/{printf "%s=%s ", $1, $2}')"
for i in enp1s0f1np1 enP2p1s0f1np1; do
  echo "--- $i"
  ip -d link show $i 2>/dev/null | grep -oE "mtu [0-9]+|state [A-Z]+" | tr '\n' ' '; echo
  echo -n "speed/link: "; ethtool $i 2>/dev/null | awk -F': ' '/Speed|Link detected|Auto-negotiation/{printf "%s=%s ", $1, $2}'; echo
  echo -n "pause: "; ethtool -a $i 2>/dev/null | tr -s '\t\n ' ' ' | cut -c1-110; echo
  echo -n "priv-flags(pfc/dcb): "; ethtool --show-priv-flags $i 2>/dev/null | grep -iE "pfc|dcb|rx_cqe|cqe_compress" | tr -s ' ' | tr '\n' ';'; echo
  echo -n "rx prio packets: "; ethtool -S $i 2>/dev/null | awk '/rx_prio[0-9]_packets/ && $2>0{printf "%s=%s ", $1, $2}'; echo
  echo -n "tx prio packets: "; ethtool -S $i 2>/dev/null | awk '/tx_prio[0-9]_packets/ && $2>0{printf "%s=%s ", $1, $2}'; echo
  echo -n "pfc/pause/ecn/cnp counters: "; ethtool -S $i 2>/dev/null | awk '/(prio[0-9]_pause|pause_ctrl|ecn_marked|cnp|buffer_discard|discards_phy|out_of_buffer|crc_errors|symbol_err|corrected_bits|link_down)/ && $2>0{printf "%s=%s ", $1, $2}'; echo
done
for d in rocep1s0f1 roceP2p1s0f1; do
  echo "--- rdma $d"
  echo -n "tos/traffic_class: "; cat /sys/class/infiniband/$d/tc/1/traffic_class 2>/dev/null | tr '\n' ' '; echo
  echo -n "cma_roce_tos: "; cat /sys/kernel/config/rdma_cm/$d/ports/1/default_roce_tos 2>/dev/null; echo
  echo -n "active_mtu/state: "; cat /sys/class/infiniband/$d/ports/1/{state,phys_state,rate} 2>/dev/null | tr '\n' ' '; echo
  echo -n "fw: "; cat /sys/class/infiniband/$d/fw_ver 2>/dev/null; 
done
echo "--- mlnx_qos (may need root)"; (mlnx_qos -i enp1s0f1np1 2>&1 | head -24) || echo "mlnx_qos absent"
echo "--- lldp/dcb tools"; command -v lldptool dcb mlnx_qos mlxconfig 2>&1 | tr '\n' ' '; echo
echo "--- tcp_ecn=$(cat /proc/sys/net/ipv4/tcp_ecn)  nic irq/ring: $(ethtool -g enp1s0f1np1 2>/dev/null | awk '/Current/{f=1} f&&/RX:|TX:/{printf "%s ", $0}')"
echo "--- pcie link: $(lspci -s 0000:01:00.1 -vv 2>/dev/null | grep -E 'LnkSta:' | tr -s ' ' | head -1)"
echo "--- fabric netplan/mtu files"; grep -rhE "mtu|10\.7[34]\." /etc/netplan/*.yaml 2>/dev/null | tr -s ' ' | head -8
