import socket
import random

SERVER_IP = 'localhost'
SERVER_PORT = 12345

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server_socket.bind((SERVER_IP, SERVER_PORT))

expected_seq = 0

print("Servidor esperando quadros...")

while True:
    frame, addr = server_socket.recvfrom(1024)
    seq_num, data = frame.decode().split(":")

    seq_num = int(seq_num)

    # Simular perda de pacote (ex: 30% de perda)
    if random.random() < 0.3:
        print(f"Quadro {seq_num} perdido (simulado).")
        continue

    if seq_num == expected_seq:
        print(f"Quadro {seq_num} recebido corretamente: {data}")
        server_socket.sendto(str(seq_num).encode(), addr)
        expected_seq += 1
    else:
        print(f"Quadro {seq_num} fora de ordem. Esperando {expected_seq}...")
        # Reenviar último ACK correto
        server_socket.sendto(str(expected_seq - 1).encode(), addr)
