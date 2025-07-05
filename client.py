import socket
import time

def send_frames():
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    frames = ["!0-1-Hello-CRC#", "!0-1-World-CRC#"]

    for frame in frames:
        print(f"Enviando: {frame}")
        client_socket.sendto(frame.encode(), ('localhost', 12345))
        time.sleep(1)  # Simular tempo de transmissão

    client_socket.close()

if __name__ == "__main__":
    send_frames()
