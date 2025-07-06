import socket
import threading
import time
import collections
import json

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


# Em sender.py, dentro da função listen_for_acks():

def listen_for_acks():
    """
    Thread para escutar por ACKs do receptor.
    """
    global expected_ack, running
    
    # Define um timeout para recv() para que a thread possa verificar 'running' periodicamente.
    sender_socket.settimeout(0.5) 

    while running:
        try:
            # Tenta ler o tamanho do quadro (10 bytes)
            len_bytes = sender_socket.recv(10)
            
            # Se não recebeu bytes, pode ser que o receptor fechou a conexão
            if not len_bytes:
                print("[SENDER] Receptor desconectou ou enviou dados incompletos.")
                running = False
                break
            
            # Converte o tamanho do quadro para int
            frame_len = int(len_bytes.decode('utf-8').strip())
            
            # Lê o quadro completo com base no tamanho informado
            frame_bytes = b''
            bytes_read = 0
            while bytes_read < frame_len:
                # Recebe pedaços do quadro até que o tamanho total seja atingido
                packet = sender_socket.recv(min(frame_len - bytes_read, BUFFER_SIZE))
                if not packet:
                    print("[SENDER] Receptor desconectou durante leitura do quadro.")
                    running = False
                    break
                frame_bytes += packet
                bytes_read += len(packet)
            
            # Se a flag 'running' mudou durante a leitura de bytes, sair
            if not running: break

            # Desserializa o quadro recebido para um objeto Frame
            received_frame = Frame.from_json(frame_bytes.decode('utf-8'))

            if received_frame.frame_type == 'ACK':
                ack_num = received_frame.seq_num # Este é o próximo quadro que o RECEPTOR espera
                
                with lock: # Protege o acesso às variáveis globais compartilhadas
                    print(f"\n[SENDER] Received ACK: {received_frame}")
                    print(f"  [SENDER DEBUG] Antes do processamento: expected_ack={expected_ack}, ack_num_recebido={ack_num}")
                    print(f"  [SENDER DEBUG] send_buffer antes: {list(send_buffer.keys())}")

                    # --- Lógica de AVANÇO da Janela Go-Back-N no Transmissor ---
                    # A base da janela (expected_ack) só deve avançar se o ack_num recebido
                    # indicar um NOVO progresso (ou seja, ack_num > expected_ack, considerando wraparound).
                    # Se ack_num == expected_ack, é um ACK duplicado ou reconfirmação da base atual; não há avanço.
                    
                    if seq_greater_equal(ack_num, expected_ack) and ack_num != expected_ack:
                        # Limpa os quadros do buffer e para seus timers.
                        # Percorre do 'expected_ack' antigo até o 'ack_num' recebido (não inclusivo).
                        current_seq_to_clear = expected_ack
                        while current_seq_to_clear != ack_num:
                            if current_seq_to_clear in send_buffer:
                                stop_timer(current_seq_to_clear) 
                                del send_buffer[current_seq_to_clear]
                                print(f"  [SENDER DEBUG] Removido quadro {current_seq_to_clear} do buffer.")
                            current_seq_to_clear = seq_add(current_seq_to_clear, 1)
                        
                        # Atualiza a base da janela do transmissor para o ack_num recebido.
                        print(f"  [SENDER DEBUG] Janela base (expected_ack) avançou de {expected_ack} para {ack_num}.")
                        expected_ack = ack_num
                        
                        # Se o buffer de envio agora está vazio, todos os quadros foram reconhecidos.
                        # Paramos quaisquer timers restantes para garantir uma saída limpa.
                        if not send_buffer and any(timers.values()):
                            print("[SENDER DEBUG] Buffer vazio. Parando todos os timers restantes.")
                            for timer_seq in list(timers.keys()):
                                stop_timer(timer_seq)

                    else:
                        # ACK duplicado (ack_num == expected_ack) ou ACK antigo (ack_num < expected_ack).
                        # Não causa avanço na janela, mas pode reconfirmar a necessidade de retransmissão
                        # se a base da janela estiver travada.
                        print(f"  [SENDER DEBUG] ACK {ack_num} é re-ACK/duplicado/antigo. Esperado para avanço: > {expected_ack}. Ignorando avanço.")
                    
                    print(f"  [SENDER DEBUG] send_buffer depois: {list(send_buffer.keys())}")
                    print(f"  [SENDER DEBUG] Novo expected_ack (base): {expected_ack}")

            else: # Se o tipo de quadro não for ACK, imprime e ignora
                print(f"[SENDER] Received unexpected frame type: {received_frame.frame_type}")

        except socket.timeout:
            # Se o recv() atingir o timeout, esta exceção é levantada.
            # A thread continua no loop 'while running', verificando a flag 'running'.
            pass 
        except json.JSONDecodeError:
            print("[SENDER ERROR] Falha ao decodificar JSON dos dados recebidos. Quadro possivelmente corrompido ou dados incompletos.")
        except ConnectionResetError:
            print("[SENDER] Conexão com o receptor perdida.")
            running = False
            break
        except Exception as e:
            print(f"[SENDER ERROR] Ocorreu um erro inesperado na escuta de ACKs: {e}")
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
    # Adicione esta linha para imprimir o total de quadros
    print(f"[SENDER] Total de quadros a enviar: {len(message_chunks)}")

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