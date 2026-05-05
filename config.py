"""
config.py — Configurações centralizadas do projecto EFD-REINF A3
================================================================
Todas as URLs, caminhos e parâmetros num único lugar.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos da DLL PKCS#11 (Token A3)
# ---------------------------------------------------------------------------
# Prioridade: variável de ambiente > caminhos conhecidos
PKCS11_DLL_PATH = os.environ.get(
    "PKCS11_MODULE_PATH",
    r"C:\Windows\System32\DXSafePKCS11.dll"  # AC Defesa (padrão)
)

# Caminhos alternativos comuns no Windows
PKCS11_DLL_ALTERNATIVOS = [
    r"C:\Windows\System32\DXSafePKCS11.dll",      # AC Defesa
    r"C:\Windows\System32\eTPKCS11.dll",           # SafeNet/eToken
    r"C:\Windows\System32\opensc-pkcs11.dll",      # OpenSC
    r"C:\Windows\System32\acpkcs211.dll",          # ICP-Brasil (alguns tokens)
    r"C:\Windows\System32\WDPKCS.dll",             # Watchdata
    r"C:\Windows\System32\SignatureP11.dll",       # Certisign
]

# ---------------------------------------------------------------------------
# URLs da Receita Federal — EFD-REINF
# ---------------------------------------------------------------------------
AMBIENTES = {
    "producao": {
        "recepcao": "https://reinf.receita.economia.gov.br/recepcao/lotes",
        "consulta": "https://reinf.receita.economia.gov.br/consulta/lotes/",
    },
    "homologacao": {
        "recepcao": "https://reinf.receita.economia.gov.br/recepcao/lotes",
        "consulta": "https://reinf.receita.economia.gov.br/consulta/lotes/",
    },
}

# ---------------------------------------------------------------------------
# Pastas de trabalho (relativas ao directório do projecto)
# ---------------------------------------------------------------------------
PASTA_BASE = Path(__file__).parent
PASTA_ENVIOS = PASTA_BASE / "envios"
PASTA_RECEBIDOS = PASTA_BASE / "recebidos"
PASTA_PROTOCOLOS = PASTA_BASE / "protocolos"
PASTA_RECIBOS = PASTA_BASE / "recibos"
PASTA_LOGS = PASTA_BASE / "logs"

# Criar pastas automaticamente
for pasta in [PASTA_ENVIOS, PASTA_RECEBIDOS, PASTA_PROTOCOLOS, PASTA_RECIBOS, PASTA_LOGS]:
    pasta.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Timeouts e parâmetros HTTP
# ---------------------------------------------------------------------------
HTTP_TIMEOUT = 60          # segundos
HTTP_MAX_TENTATIVAS = 3    # retentativas em caso de erro de rede
HTTP_INTERVALO_TENTATIVA = 5  # segundos entre retentativas

# ---------------------------------------------------------------------------
# Assinatura XML
# ---------------------------------------------------------------------------
XML_ALGORITHM_SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
XML_SIGNATURE_METHOD = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
XML_CANONICALIZATION = "http://www.w3.org/2001/10/xml-exc-c14n#"
XML_TRANSFORM_ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FORMATO = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_NIVEL = os.environ.get("LOG_NIVEL", "INFO").upper()
