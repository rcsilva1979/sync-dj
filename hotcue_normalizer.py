# hotcue_normalizer.py
from le_json import seconds_to_timecode

# Função para normalizar uma lista de hotcues
def normalize_hotcues(hotcues: list[dict]) -> list[dict]:
    """
    Normaliza uma lista de hotcues, ajustando seus tempos e formatando-os.
    Realiza a conversão de milissegundos para segundos e aplica uma compensação de delay.
    :param hotcues: Uma lista de dicionários representando hotcues brutos.
    :return: Uma lista de dicionários de hotcues normalizados.
    """
    normalized = []

    for c in hotcues:
        pos = c.get("pos_seconds")

        # ajuste básico inicial (vamos evoluir depois)
        if pos is None:
            continue

        if pos > 10000:  # provável ms
            pos = pos / 1000

        # Compensação do delay do encoder MP3 (aprox 1984 samples @ 44.1kHz)
        # Isso alinha os tempos da TAG Serato com os tempos calculados pelo Virtual DJ
        pos = max(0.0, pos - 0.044989)

        normalized.append({
            **c,
            "pos_seconds": float(pos),
            "time": seconds_to_timecode(pos)
        })

    return normalized