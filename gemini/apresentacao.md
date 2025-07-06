## Tipos de falha simulados

O código implementado simula três tipos de erros cruciais que afetam a transmissão de dados em uma rede e que os protocolos de camada de enlace, como o Go-Back-N, foram criados para lidar:

### Falha em enviar o Frame (Perda de Quadro de Dados):

#### Como é simulado: 
Isso acontece no transmissor (`sender.py`), dentro da função `send_frame`. Antes mesmo de o quadro ser enviado pelo socket, a função `simulate_loss(frame)` (definida em `utils.py`) é chamada. Com base na `LOSS_PROBABILITY`, o quadro pode ser "descartado" e não enviado.

#### Consequência: 
O receptor nunca recebe esse quadro. O transmissor, por sua vez, não recebe o ACK correspondente e, eventualmente, o timer para aquele quadro (ou para a base da janela, se for o quadro mais antigo não confirmado) expira. Isso dispara uma retransmissão Go-Back-N, onde o transmissor reenviará o quadro perdido e todos os subsequentes que estavam na janela.

### Falha em enviar o ACK (Perda de ACK):

#### Como é simulado: 
Isso ocorre no receptor (`receiver.py`), dentro da função send_ack. Assim que o receptor decide que deve enviar um ACK, a função `simulate_loss(ack_frame, is_ack=True)` (também em `utils.py`) é chamada. Com a `ACK_LOSS_PROBABILITY`, o ACK pode ser "descartado" antes de ser enviado de volta ao transmissor.

#### Consequência: 
O transmissor nunca recebe a confirmação de que o quadro (ou os quadros até aquele ponto) foi recebido com sucesso. Assim como na perda de quadro de dados, o timer no transmissor para o quadro correspondente (ou para a base da janela) expira, levando à retransmissão Go-Back-N.

### Frame com erro (Corrupção de Dados):

#### Como é simulado: 
Essa simulação acontece no transmissor (`sender.py`), mas representa um erro que ocorreria "no fio" durante a transmissão. A função `simulate_error(frame)` (em `utils.py`) é chamada depois que o CRC original do quadro foi calculado, mas antes do quadro ser enviado pelo socket. Ela modifica aleatoriamente um bit nos dados (`frame.data`) do quadro.

#### Consequência: 
O quadro chega ao receptor, mas seus dados estão corrompidos. No receptor (`receiver.py`), a função `verify_crc8()` é chamada para recalcular o CRC dos dados recebidos e compará-lo com o CRC original que veio no quadro. Como o dado foi alterado, o CRC recalculado será diferente do original. O receptor detecta o erro, descarta o quadro corrompido e, crucialmente, reenvia o ACK para o `expected_seq_num` (o último quadro correto que ele espera). Isso sinaliza ao transmissor que ele ainda está esperando por aquele quadro específico, o que, novamente, leva à retransmissão Go-Back-N (seja por timeout ou por ACKs duplicados do receptor).