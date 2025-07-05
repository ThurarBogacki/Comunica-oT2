import json
import time

# --- Constantes de Rede ---
HOST = '127.0.0.1'  # Endereço IP do localhost
PORT = 12345        # Porta para o receptor escutar e o transmissor conectar
BUFFER_SIZE = 1024  # Tamanho do buffer para receber dados (ajustar conforme necessário)

# --- Constantes de Protocolo ---
WINDOW_SIZE = 4     # Tamanho da janela Go-Back-N
TIMEOUT = 2         # Tempo de espera (em segundos) antes de retransmitir
MAX_SEQ_NUM = 7     # Número máximo de sequência (para janela de 8, 0 a 7, M=3 bits)
                    # Go-Back-N: tamanho da janela N <= 2^M - 1. Aqui, 4 <= 2^3 - 1 (7).

# --- Probabilidades de Simulação de Erros/Perdas ---
LOSS_PROBABILITY = 0.2     # 20% de chance de um quadro de dados ser "perdido" (não enviado)
ERROR_PROBABILITY = 0.2    # 20% de chance de um quadro de dados ser "corrompido"
ACK_LOSS_PROBABILITY = 0.3 # 30% de chance de um ACK ser "perdido" (não enviado)

# --- Classe para Representar um Quadro (Frame) ---
class Frame:
    def __init__(self, seq_num, frame_type, data=None, crc=None):
        """
        Inicializa um objeto Frame.
        :param seq_num: Número de sequência do quadro.
        :param frame_type: Tipo do quadro ('DATA' ou 'ACK').
        :param data: Dados do quadro (payload).
        :param crc: Valor CRC do quadro.
        """
        self.seq_num = seq_num
        self.frame_type = frame_type
        self.data = data
        self.crc = crc

    def to_json(self):
        """Converte o objeto Frame para uma string JSON."""
        return json.dumps(self.__dict__)

    @staticmethod
    def from_json(json_str):
        """Cria um objeto Frame a partir de uma string JSON."""
        data = json.loads(json_str)
        # Usamos .get() para lidar com o caso de ACKs não terem 'data' ou 'crc'
        frame = Frame(data['seq_num'], data['frame_type'], data.get('data'), data.get('crc'))
        return frame

    def __str__(self):
        """Representação em string do objeto Frame."""
        return f"Frame(Seq={self.seq_num}, Type={self.frame_type}, Data='{self.data[:20] if self.data else 'None'}...', CRC={hex(self.crc) if self.crc is not None else 'None'})"

# --- Funções de Controle de Erro (CRC-8) ---
# Polinômio gerador para CRC-8 (0x07 = x^8 + x^2 + x + 1)
# Este é um dos muitos polinômios possíveis para CRC-8.
CRC8_POLYNOMIAL = 0x07

def calculate_crc8(data_bytes):
    """
    Calcula o CRC-8 para uma sequência de bytes.
    Implementação bit-a-bit do CRC-8.
    """
    crc = 0x00  # Valor inicial do CRC
    for byte in data_bytes:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:  # Se o bit mais significativo for 1
                crc = (crc << 1) ^ CRC8_POLYNOMIAL
            else:
                crc <<= 1
            crc &= 0xFF  # Garante que o CRC permaneça em 8 bits
    return crc

def verify_crc8(data_bytes, received_crc):
    """
    Verifica se o CRC calculado para data_bytes corresponde ao received_crc.
    """
    calculated_crc = calculate_crc8(data_bytes)
    return calculated_crc == received_crc

# --- Funções de Simulação de Eventos de Rede ---
def simulate_loss(frame, is_ack=False):
    """Simula a perda de um quadro (DATA ou ACK)."""
    prob = ACK_LOSS_PROBABILITY if is_ack else LOSS_PROBABILITY
    if random.random() < prob:
        print(f"SIMULANDO: {'ACK' if is_ack else 'Quadro DATA'} {frame.seq_num} PERDIDO.")
        return True # Perda simulada
    return False # Não houve perda

def simulate_error(frame):
    """Simula a introdução de um erro em um quadro DATA."""
    if frame.frame_type == 'DATA' and random.random() < ERROR_PROBABILITY:
        print(f"SIMULANDO: Introduzindo ERRO no Quadro DATA {frame.seq_num}")
        # Corrompe um bit aleatório nos dados do quadro
        if frame.data:
            data_bytes = bytearray(frame.data.encode('utf-8'))
            if data_bytes:
                byte_index = random.randint(0, len(data_bytes) - 1)
                bit_mask = 1 << random.randint(0, 7)
                data_bytes[byte_index] ^= bit_mask  # Inverte um bit
                # Decodifica de volta, mas a corrupção deve ser detectada pelo CRC no receptor
                frame.data = data_bytes.decode('utf-8', errors='ignore')
        return True # Erro simulado
    return False # Não houve erro

import random # Importe random aqui para as funções de simulação