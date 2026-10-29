"""Guard the fixture Python processes; never connect to an unowned service."""
import json
import os
from pathlib import Path
import socket
import sys

if os.environ.get('P2Z_VERIFY_PORTS'):
    registry = Path(os.environ['P2Z_VERIFY_PORTS'])
    original_bind = socket.socket.bind

    def bind_owned(sock, address):
        if sock.family not in (socket.AF_INET, socket.AF_INET6) or address[0] != '127.0.0.1' or address[1] != 0:
            raise OSError('verification permits only owned ephemeral IPv4 peers')
        result = original_bind(sock, address)
        with registry.open('a') as stream:
            stream.write(str(sock.getsockname()[1]) + '\n')
        return result

    socket.socket.bind = bind_owned

    def guard(event, args):
        if event == 'socket.connect':
            address = args[1]
            ports = registry.read_text().splitlines()
            allowed = isinstance(address, tuple) and address[0] == '127.0.0.1' and str(address[1]) in ports
            with Path(os.environ['P2Z_VERIFY_NETWORK']).open('a') as stream:
                stream.write(json.dumps({'address': address, 'allowed': allowed}) + '\n')
            if not allowed:
                raise OSError('verification blocked unowned network endpoint')
        elif event == 'socket.getaddrinfo' and args[0] not in ('127.0.0.1', 'localhost', b'127.0.0.1'):
            raise OSError('verification blocked external DNS')

    sys.addaudithook(guard)
