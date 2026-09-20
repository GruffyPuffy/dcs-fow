#!/usr/bin/env python3
"""One request to the candidate FoW hook on the Ubuntu host."""
import argparse
import socket

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("request", choices=("PING", "STATUS", "BLUE_MOVE_TEST"))
args = parser.parse_args()

with socket.create_connection(("127.0.0.1", 10309), timeout=3) as connection:
    connection.settimeout(3)
    connection.sendall((args.request + "\n").encode("ascii"))
    with connection.makefile("r", encoding="utf-8", newline="\n") as stream:
        answer = stream.readline(2048)
        if not answer or not answer.endswith("\n"):
            raise SystemExit("No complete response from DCS hook")
        print(answer.rstrip("\n"))
