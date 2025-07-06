import socket
import threading
import json
import time
import json

from utils import (
    HOST, PORT, BUFFER_SIZE, MAX_SEQ_NUM,
    Frame, calculate_crc8, verify_crc8, simulate_loss, ACK_LOSS_PROBABILITY
)

# --- Variáveis Globais do Receptor ---
expected_seq_num = 0    # Próximo número de sequência de dados esperado
received_message = []   # Lista para armazenar as partes da mensagem recebida em ordem
receiver_socket = None
client_conn = None
client_addr = None
running = True          # Flag para controlar o loop principal

# --- Funções do Receptor ---
def seq_add(seq, val):
    """Adiciona um valor ao número de sequência, com wraparound."""
    return (seq + val) % (MAX_SEQ_NUM + 1)

def send_ack(conn, ack_num):
    """
    Envia um quadro ACK para o transmissor, aplicando simulação de perda.
    """
    ack_frame = Frame(ack_num, 'ACK')
    if simulate_loss(ack_frame, is_ack=True): # Simula perda do ACK
        return

    try:
        ack_str = ack_frame.to_json()
        ack_bytes = ack_str.encode('utf-8')
        ack_len = len(ack_bytes)

        # Envia o tamanho do ACK e o ACK
        conn.sendall(str(ack_len).zfill(10).encode('utf-8'))
        conn.sendall(ack_bytes)
        print(f"[RECEIVER] Sent ACK for Seq={ack_num}")
    except Exception as e:
        print(f"[RECEIVER ERROR] Failed to send ACK: {e}")

def main_receiver():
    global receiver_socket, client_conn, client_addr, expected_seq_num, running

    last_accepted_seq = None  # Adicione esta linha para controlar o último seq_num aceito

    receiver_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    receiver_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Permite reuso do endereço
    receiver_socket.settimeout(1) # Timeout para accept()

    try:
        receiver_socket.bind((HOST, PORT))
        receiver_socket.listen(1)
        print(f"[RECEIVER] Listening on {HOST}:{PORT}")

        client_conn, client_addr = receiver_socket.accept()
        print(f"[RECEIVER] Conectado ao transmissor em {client_addr}")

        while running:
            try:
                # Lê o tamanho do próximo quadro
                len_bytes = client_conn.recv(10)
                if not len_bytes:
                    print("[RECEIVER] Transmissor desconectou.")
                    running = False
                    break
                
                frame_len = int(len_bytes.decode('utf-8').strip())
                
                # Lê o quadro completo
                frame_bytes = b''
                while len(frame_bytes) < frame_len:
                    packet = client_conn.recv(min(frame_len - len(frame_bytes), BUFFER_SIZE))
                    if not packet:
                        print("[RECEIVER] Transmissor desconectou durante leitura do quadro.")
                        running = False
                        break
                    frame_bytes += packet
                
                if not running: break # Se a flag mudou durante a leitura

                received_frame = Frame.from_json(frame_bytes.decode('utf-8'))
                
                if received_frame.frame_type == 'DATA':
                    print(f"[RECEIVER] Received: {received_frame}")

                    # --- Verificação de CRC ---
                    data_for_crc_check = received_frame.data.encode('utf-8')
                    
                    if not verify_crc8(data_for_crc_check, received_frame.crc):
                        print(f"[RECEIVER] ERRO DE CRC detectado no Quadro {received_frame.seq_num}. Descartando.")
                        send_ack(client_conn, expected_seq_num)
                        continue

                    # --- Controle de Fluxo (Go-Back-N) ---
                    if received_frame.seq_num == expected_seq_num:
                        if last_accepted_seq != expected_seq_num:
                            print(f"[RECEIVER] Quadro {received_frame.seq_num} recebido em ordem. Aceitando.")
                            received_message.append(received_frame.data)
                            last_accepted_seq = expected_seq_num
                        else:
                            print(f"[RECEIVER] Quadro {received_frame.seq_num} duplicado. Ignorando.")
                        expected_seq_num = seq_add(expected_seq_num, 1)
                        send_ack(client_conn, expected_seq_num)
                    else:
                        # Quadro fora de ordem (número de sequência diferente do esperado)
                        # No Go-Back-N, descartamos quadros fora de ordem e retransmitimos o último ACK.
                        print(f"[RECEIVER] Quadro {received_frame.seq_num} fora de ordem. Esperado: {expected_seq_num}. Descartando.")
                        send_ack(client_conn, expected_seq_num) # Reenvia o ACK para o próximo esperado
                else:
                    print(f"[RECEIVER] Received unexpected frame type: {received_frame.frame_type}")

            except json.JSONDecodeError:
                print("[RECEIVER ERROR] Failed to decode JSON from received data. Possibly corrupted frame or incomplete data.")
            except socket.timeout:
                # Nenhum dado recebido no período do timeout do socket, apenas continua
                pass
            except ConnectionResetError:
                print("[RECEIVER] Conexão com o transmissor perdida.")
                running = False
            except Exception as e:
                print(f"[RECEIVER ERROR] An unexpected error occurred: {e}")
                running = False

    except socket.timeout:
        print("[RECEIVER] Tempo limite para aceitar conexão excedido. Nenhuma conexão recebida.")
    except Exception as e:
        print(f"[RECEIVER ERROR] An error occurred during setup or listening: {e}")
    finally:
        running = False
        if client_conn:
            client_conn.close()
            print("[RECEIVER] Conexão do cliente fechada.")
        if receiver_socket:
            receiver_socket.close()
            print("[RECEIVER] Socket do receptor fechado.")
        
        print("\n--- Mensagem Final Recebida ---")
        print("".join(received_message))
        print("-------------------------------")

if __name__ == "__main__":
    main_receiver()