import socket
import time

# Configurações
SERVER_IP = 'localhost'
SERVER_PORT = 12345
WINDOW_SIZE = 4
TIMEOUT = 2

# Dados simulados
frames = ["Frame1", "Frame2", "Frame3", "Frame4", "Frame5", "Frame6"]

client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
client_socket.settimeout(TIMEOUT)

base = 0
next_seq = 0

while base < len(frames):
    # Enviar até o tamanho da janela
    while next_seq < base + WINDOW_SIZE and next_seq < len(frames):
        print(f"Enviando: {frames[next_seq]}")
        client_socket.sendto(f"{next_seq}:{frames[next_seq]}".encode(), (SERVER_IP, SERVER_PORT))
        next_seq += 1

    try:
        # Esperar ACK
        ack, _ = client_socket.recvfrom(1024)
        ack_num = int(ack.decode())
        print(f"ACK recebido: {ack_num}")
        base = ack_num + 1  # Mover a base da janela
    except socket.timeout:
        print("Timeout! Reenviando a janela...")
        # Reenviar toda a janela a partir de base
        next_seq = base

print("Todos os quadros enviados com sucesso.")
client_socket.close()
