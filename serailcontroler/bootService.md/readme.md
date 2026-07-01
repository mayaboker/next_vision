

S99_next_proxy.sh	=> /etc/init.d/S99_next_proxy.sh
next-proxy.service	=> /etc/systemd/system/next-proxy.service

sudo systemctl daemon-reload
sudo systemctl enable next-proxy.service
sudo systemctl start next-proxy.service
sudo systemctl status next-proxy.service

