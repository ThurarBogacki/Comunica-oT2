import socket
import threading
import time
import collections

from utils import (
    HOST, PORT, BUFFER_SIZE, WINDOW_SIZE, TIMEOUT, MAX_SEQ_NUM,
    Frame, calculate_crc8, simulate_loss, simulate_error
)

# --- Variáveis Globais do Transmissor ---
sender_socket = None
sequence_number = 0         # Número de sequência do próximo quadro a ser enviado
expected_ack = 0            # Próximo ACK esperado (janela base)
send_buffer = collections.OrderedDict() # Buffer de quadros enviados (seq_num: Frame)
timers = {}                 # Dicionário de timers (seq_num: threading.Timer)
lock = threading.Lock()     # Lock para sincronização de threads
running = True              # Flag para controlar o loop de envio e recebimento

# --- Funções do Transmissor ---
def send_frame(conn, frame):
    """
    Envia um quadro para o receptor, aplicando simulações de erro/perda.
    """
    if simulate_loss(frame): # Simula perda antes de enviar
        return

    # Se for um quadro de dados, simula a introdução de erro antes do envio
    # mas APÓS o CRC ser calculado, simulando erro no meio de transmissão.
    # O CRC que está no frame é o original, o receiver vai detectar a diferença.
    original_crc = frame.crc
    if simulate_error(frame):
        # Apenas para a simulação, se o erro for introduzido, não alteramos o CRC original
        # O receptor irá calcular um CRC diferente e detectar o erro
        pass

    try:
        frame_str = frame.to_json()
        frame_bytes = frame_str.encode('utf-8')
        frame_len = len(frame_bytes)

        # Envia o tamanho do quadro primeiro (com padding para garantir 10 dígitos)
        conn.sendall(str(frame_len).zfill(10).encode('utf-8'))
        # Envia o quadro completo
        conn.sendall(frame_bytes)

        if frame.frame_type == 'DATA':
            print(f"[SENDER] Sent: {frame}")
        elif frame.frame_type == 'ACK':
            print(f"[SENDER] Sent ACK: {frame}") # (Em caso de ACK de volta, o que não acontece no Go-Back-N padrão de dados)
    except Exception as e:
        print(f"[SENDER ERROR] Failed to send frame: {e}")

def retransmit_from(start_seq_num):
    """
    Retransmite todos os quadros a partir de start_seq_num (Go-Back-N).
    """
    with lock:
        print(f"\n[SENDER] Timeout ou ACK inesperado para Seq={start_seq_num}. Retransmitindo do quadro {start_seq_num}...")
        frames_to_retransmit = []
        for seq, frame in send_buffer.items():
            if seq_greater_equal(seq, start_seq_num):
                frames_to_retransmit.append(frame)
        
        # Para evitar problemas com iteração durante modificação, retransmita após coletar
        for frame in frames_to_retransmit:
            # Cancela e reinicia o timer para o quadro que causou o timeout
            if frame.seq_num in timers:
                timers[frame.seq_num].cancel()
            
            # Recalcula CRC para os dados atuais (caso tenham sido alterados por simulação de erro)
            # Para garantir que o CRC enviado com o quadro retransmitido seja o correto para os dados atuais
            if frame.frame_type == 'DATA' and frame.data:
                frame.crc = calculate_crc8(frame.data.encode('utf-8'))
            
            send_frame(sender_socket, frame) # Envia o quadro
            # Reinicia o timer para este quadro retransmitido
            start_timer(sender_socket, frame.seq_num)

def start_timer(conn, seq_num):
    """Inicia um timer para um quadro."""
    if seq_num in timers:
        timers[seq_num].cancel() # Cancela timer anterior se existir
    
    # Adiciona o seq_num ao argumento para saber qual timer expirou
    timer = threading.Timer(TIMEOUT, retransmit_from, args=(seq_num,)) 
    timers[seq_num] = timer
    timer.start()

def stop_timer(seq_num):
    """Para o timer de um quadro específico."""
    if seq_num in timers:
        timers[seq_num].cancel()
        del timers[seq_num]

def seq_add(seq, val):
    """Adiciona um valor ao número de sequência, com wraparound."""
    return (seq + val) % (MAX_SEQ_NUM + 1)

def seq_greater_equal(s1, s2):
    """Verifica se s1 >= s2 considerando o wraparound."""
    # S1 é maior ou igual a S2 se eles estiverem na mesma "metade" do círculo
    # e S1 estiver à frente de S2, ou se S1 estiver na metade inicial e S2 na final
    # (indicando que S1 "passou" por S2 no wraparound)
    if s1 == s2:
        return True
    
    # Caso 1: Ambos os números estão próximos
    if abs(s1 - s2) <= MAX_SEQ_NUM / 2:
        return s1 > s2
    
    # Caso 2: Houve wraparound
    return s1 < s2


def listen_for_acks():
    """
    Thread para escutar por ACKs do receptor.
    """
    global expected_ack, running
    while running:
        try:
            # Lê o tamanho do próximo quadro
            len_bytes = sender_socket.recv(10)
            if not len_bytes:
                print("[SENDER] Receptor desconectou.")
                running = False
                break
            
            frame_len = int(len_bytes.decode('utf-8').strip())
            
            # Lê o quadro completo
            frame_bytes = b''
            while len(frame_bytes) < frame_len:
                packet = sender_socket.recv(min(frame_len - len(frame_bytes), BUFFER_SIZE))
                if not packet:
                    print("[SENDER] Receptor desconectou durante leitura do quadro.")
                    running = False
                    break
                frame_bytes += packet
            
            if not running: break

            received_frame = Frame.from_json(frame_bytes.decode('utf-8'))

            if received_frame.frame_type == 'ACK':
                ack_num = received_frame.seq_num
                with lock:
                    print(f"[SENDER] Received ACK: {received_frame}")

                    # Se o ACK for para o próximo quadro esperado (expected_ack)
                    # ou para um quadro posterior, significa que ele confirmou
                    # todos os quadros até ack_num.
                    # No Go-Back-N, um ACK N significa que o receptor está
                    # esperando o quadro N, confirmando N-1 e todos os anteriores.
                    # Ou seja, o ACK é para o próximo quadro a ser RECEBIDO.
                    # Se o ACK é para N, significa que N-1 foi o último recebido com sucesso.
                    
                    # Logica para Go-Back-N: o ACK é cumulativo.
                    # O ACK N confirma que todos os quadros até N-1 foram recebidos.
                    # Portanto, a janela base avança para N.
                    
                    # Verifica se o ACK recebido é válido e avança a janela
                    # (o ACK é para expected_ack, ou seja, ack_num = expected_ack)
                    # Ou um ACK para um número de sequência maior, o que significa que
                    # o receptor já recebeu quadros além do esperado.
                    # Isso é importante para lidar com ACKs duplicados ou fora de ordem
                    # que podem ocorrer devido a retransmissões.
                    
                    # A janela desliza até o ack_num (que é o próximo esperado)
                    # Então, todos os quadros até (ack_num - 1) são confirmados.

                    # Para Go-Back-N, 'expected_ack' é o próximo seq_num que o *remetente*
                    # espera que o *receptor* envie um ACK para (ou seja, o próximo frame que
                    # o remetente vai enviar, e o receptor está esperando receber).
                    
                    # O ACK que vem do receptor é o *próximo* quadro de DADOS que ele está esperando.
                    # Ou seja, se o receptor envia ACK(5), ele recebeu 4 e está esperando 5.
                    # Portanto, todos os quadros até 4 estão confirmados. Nossa janela pode avançar para 5.

                    while True:
                        # Verifica se o ACK confirma o quadro atual da base da janela
                        # seq_add(expected_ack, 0) == expected_ack
                        # Este loop é necessário se o ACK recebido for para um quadro
                        # muito à frente, confirmando múltiplos quadros.
                        if seq_greater_equal(ack_num, expected_ack):
                            if expected_ack in send_buffer:
                                stop_timer(expected_ack)
                                del send_buffer[expected_ack]
                                print(f"[SENDER] Janela base avançou para {seq_add(expected_ack, 1)}. Removido {expected_ack} do buffer.")
                            expected_ack = seq_add(expected_ack, 1) # Avança a base da janela
                            
                            if expected_ack == ack_num: # Chegou ao ACK recebido
                                break
                        else:
                            # ACK inesperado (talvez um ACK duplicado para algo já confirmado)
                            # Ou ACK para um quadro que já está fora da janela
                            print(f"[SENDER] ACK inesperado recebido: {ack_num}. Esperado: {expected_ack}. Ignorando.")
                            break # Sai do loop se o ACK não estiver na frente da janela esperada
                    
                    # Se todos os quadros da janela foram confirmados, não há timers rodando
                    # Se não, o timer do quadro mais antigo não confirmado ainda deve estar rodando.
                    # Se um timer expira para 'expected_ack', ele retransmite de 'expected_ack'
            else:
                print(f"[SENDER] Received unexpected frame type: {received_frame.frame_type}")

        except json.JSONDecodeError:
            print("[SENDER ERROR] Failed to decode JSON from received data.")
        except ConnectionResetError:
            print("[SENDER] Conexão com o receptor perdida.")
            running = False
        except socket.timeout:
            # Este timeout é para recv, não para os timers dos quadros
            pass
        except Exception as e:
            print(f"[SENDER ERROR] An error occurred in ACK listener: {e}")
            running = False

def main_sender():
    global sender_socket, sequence_number, running

    message = (
        "Este é um exemplo de mensagem longa a ser enviada usando Go-Back-N. "
        "Os quadros serão divididos e enviados um por um. "
        "Vamos testar a resiliência do protocolo contra perdas e erros. "
        "Cada pedaço desta mensagem se tornará um quadro, e o sistema "
        "lidará com quaisquer problemas de transmissão que ocorram. "
        "Espero que o receptor consiga remontar tudo corretamente! "
        "Esta é a segunda parte da mensagem, com mais informações para testar "
        "a capacidade de recuperação. Se houver falhas, o Go-Back-N "
        "deverá garantir que todos os dados cheguem, mesmo que demore mais. "
        "A integridade dos dados é crucial, por isso o CRC entra em cena. "
        "Terceira parte: estamos enviando dados adicionais para garantir "
        "que o buffer do transmissor e do receptor sejam bem utilizados. "
        "A janela deslizante permite o envio de múltiplos quadros sem ACK imediato, "
        "melhorando a eficiência, mas exigindo retransmissões em cascata "
        "se um quadro for perdido. Quarta parte: continuar testando a robustez "
        "com mais texto. Quanto mais texto, maior a chance de erros ou perdas "
        "simuladas ocorrerem, e podemos observar o protocolo em ação. "
        "Isso demonstra como a camada de enlace garante a confiabilidade "
        "sobre um canal não confiável. Última parte da mensagem: "
        "Concluímos o envio e esperamos a confirmação final. "
        "Obrigado por acompanhar a demonstração!")
    
    # Divide a mensagem em pedaços (quadros)
    chunk_size = BUFFER_SIZE // 2 # Cada quadro terá metade do tamanho do buffer de rede para deixar espaço para o cabeçalho
    message_chunks = [message[i:i + chunk_size] for i in range(0, len(message), chunk_size)]
    
    sender_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sender_socket.settimeout(1) # Timeout para operações de socket (recv, accept)

    try:
        sender_socket.connect((HOST, PORT))
        print(f"[SENDER] Conectado ao receptor em {HOST}:{PORT}")

        # Inicia thread para escutar por ACKs
        ack_listener_thread = threading.Thread(target=listen_for_acks)
        ack_listener_thread.daemon = True # Permite que a thread termine quando a principal terminar
        ack_listener_thread.start()

        data_index = 0 # Índice do pedaço de dados a ser enviado
        while running and (data_index < len(message_chunks) or len(send_buffer) > 0):
            with lock:
                # Envia novos quadros enquanto a janela não estiver cheia e houver dados
                while len(send_buffer) < WINDOW_SIZE and data_index < len(message_chunks):
                    current_data = message_chunks[data_index]
                    
                    # Prepara o quadro
                    frame_data_bytes = current_data.encode('utf-8')
                    frame_crc = calculate_crc8(frame_data_bytes)
                    frame = Frame(sequence_number, 'DATA', current_data, frame_crc)

                    send_buffer[sequence_number] = frame # Adiciona ao buffer de envio
                    
                    send_frame(sender_socket, frame) # Envia o quadro
                    start_timer(sender_socket, sequence_number) # Inicia o timer para este quadro

                    sequence_number = seq_add(sequence_number, 1) # Avança o número de sequência
                    data_index += 1
            
            time.sleep(0.1) # Pequeno atraso para evitar CPU-bound loop

        print("\n[SENDER] Todos os dados foram enviados ou não há mais dados para enviar.")
        
        # Espera um pouco para garantir que todos os ACKs finais sejam recebidos
        # Isso é simplificado; em um sistema real, haveria um handshake de término
        # ou espera ativa por todos os ACKs.
        timeout_final = time.time() + TIMEOUT * 2
        while len(send_buffer) > 0 and time.time() < timeout_final:
            time.sleep(0.5)

    except ConnectionRefusedError:
        print("[SENDER ERROR] Conexão recusada. Verifique se o receptor está rodando.")
    except Exception as e:
        print(f"[SENDER ERROR] An unexpected error occurred: {e}")
    finally:
        running = False
        if sender_socket:
            sender_socket.close()
            print("[SENDER] Socket fechado.")

        # Cancela todos os timers restantes
        for timer in timers.values():
            timer.cancel()
        print("[SENDER] Todos os timers cancelados.")

if __name__ == "__main__":
    main_sender()