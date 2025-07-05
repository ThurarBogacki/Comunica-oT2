import socket

def start_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind(('localhost', 12345))
    print("Servidor esperando quadros...")

    while True:
        frame, addr = server_socket.recvfrom(1024)
        frame = frame.decode()
        print(f"Quadro recebido: {frame}")

if __name__ == "__main__":
    start_server()
