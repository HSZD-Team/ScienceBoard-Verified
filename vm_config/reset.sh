#!/bin/bash

CONN_NAME=$(nmcli -t -f NAME,TYPE connection show | grep ethernet | cut -d: -f1)

if [ -z "$CONN_NAME" ]; then
    exit 1
fi

nmcli connection down "$CONN_NAME"
sleep 2
nmcli connection up "$CONN_NAME"
