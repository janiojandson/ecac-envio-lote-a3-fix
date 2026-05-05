"""
certificado_a3.py — Gestão do Token A3 via PKCS#11
====================================================
Classe TokenA3Manager para:
  • Listagem de slots
  • Login com PIN
  • Extração do certificado X.509
  • Assinatura digital SHA-256 + RSA
  • Context manager para sessão automática

Dependências:
  - PyKCS11        → pip install PyKCS11
  - cryptography   → pip install cryptography
"""

import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Generator, List, Optional, Tuple

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import condicional do PyKCS11
# ---------------------------------------------------------------------------
try:
    import PyKCS11
    from PyKCS11 import PyKCS11Lib, PyKCS11Error

    HAS_PYKCS11 = True
except ImportError:
    HAS_PYKCS11 = False
    logger.warning(
        "PyKCS11 não instalado. Execute: pip install PyKCS11"
    )


# ---------------------------------------------------------------------------
# Exceções específicas
# ---------------------------------------------------------------------------
class ErroTokenA3(Exception):
    """Exceção base para erros do Token A3."""


class BibliotecaPKCS11NaoEncontrada(ErroTokenA3):
    """A biblioteca PKCS#11 não foi encontrada."""


class TokenAusente(ErroTokenA3):
    """Nenhum token A3 encontrado."""


class PINInvalido(ErroTokenA3):
    """PIN incorreto."""

    def __init__(self, tentativas_restantes: Optional[int] = None):
        self.tentativas_restantes = tentativas_restantes
        msg = "PIN incorreto."
        if tentativas_restantes is not None:
            msg += f" Tentativas restantes: {tentativas_restantes}"
        super().__init__(msg)


class PINBloqueado(ErroTokenA3):
    """PIN bloqueado após múltiplas tentativas."""


class SessaoExpirada(ErroTokenA3):
    """Sessão PKCS#11 expirada."""


class CertificadoNaoEncontrado(ErroTokenA3):
    """Nenhum certificado X.509 encontrado no token."""


class ChavePrivadaNaoEncontrada(ErroTokenA3):
    """Nenhuma chave privada de assinatura encontrada."""


class ErroAssinatura(ErroTokenA3):
    """Falha na operação de assinatura."""


# ---------------------------------------------------------------------------
# Detecção automática da DLL
# ---------------------------------------------------------------------------
_DLL_CANDIDATOS_WINDOWS = [
    r"C:\Windows\System32\DXSafePKCS11.dll",      # AC Defesa
    r"C:\Windows\System32\eTPKCS11.dll",           # SafeNet/eToken
    r"C:\Windows\System32\opensc-pkcs11.dll",      # OpenSC
    r"C:\Windows\System32\acpkcs211.dll",          # ICP-Brasil
    r"C:\Windows\System32\WDPKCS.dll",             # Watchdata
    r"C:\Windows\System32\SignatureP11.dll",       # Certisign
    r"C:\Windows\System32\cmP11.dll",              # G+D
]

_DLL_CANDIDATOS_LINUX = [
    "/usr/lib/opensc-pkcs11.so",
    "/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so",
    "/usr/lib64/opensc-pkcs11.so",
    "/usr/local/lib/opensc-pkcs11.so",
]


def detectar_dll(caminho_forcado: Optional[str] = None) -> str:
    """
    Localiza a biblioteca PKCS#11 do sistema.

    Prioridade:
      1. caminho_forcado (parâmetro)
      2. Variável PKCS11_MODULE_PATH
      3. Caminhos conhecidos por SO
    """
    if caminho_forcado:
        if Path(caminho_forcado).is_file():
            return caminho_forcado
        raise BibliotecaPKCS11NaoEncontrada(
            f"Caminho forçado não existe: {caminho_forcado}"
        )

    env_path = os.environ.get("PKCS11_MODULE_PATH", "")
    if env_path and Path(env_path).is_file():
        return env_path

    candidatos = (
        _DLL_CANDIDATOS_WINDOWS if sys.platform == "win32"
        else _DLL_CANDIDATOS_LINUX
    )

    for caminho in candidatos:
        if Path(caminho).is_file():
            logger.debug("DLL PKCS#11 detectada: %s", caminho)
            return caminho

    raise BibliotecaPKCS11NaoEncontrada(
        "Nenhuma biblioteca PKCS#11 encontrada.\n"
        "No Windows, verifique se o driver do Token A3 está instalado.\n"
        "Ou defina a variável PKCS11_MODULE_PATH com o caminho da DLL."
    )


# ---------------------------------------------------------------------------
# TokenA3Manager
# ---------------------------------------------------------------------------
class TokenA3Manager:
    """
    Gestor de sessão com Token A3 via PKCS#11.

    Uso básico:
        token = TokenA3Manager(dll_path="C:\\Windows\\System32\\DXSafePKCS11.dll")
        token.conectar()
        token.login("123456")
        cert_pem = token.obter_certificado_pem()
        assinatura = token.assinar(dados_bytes)
        token.logout()
        token.desconectar()

    Uso como context manager:
        with TokenA3Manager() as token:
            token.login("123456")
            cert_pem = token.obter_certificado_pem()
            assinatura = token.assinar(dados_bytes)
    """

    def __init__(self, dll_path: Optional[str] = None):
        if not HAS_PYKCS11:
            raise ErroTokenA3(
                "PyKCS11 não instalado. Execute: pip install PyKCS11"
            )

        self._dll_path = detectar_dll(dll_path)
        self._pkcs11: Optional[PyKCS11Lib] = None
        self._sessao = None
        self._slot = None
        self._certificado_der: Optional[bytes] = None
        self._certificado_pem: Optional[str] = None
        self._chave_privada = None
        self._logado = False

        logger.info("TokenA3Manager inicializado. DLL: %s", self._dll_path)

    def __enter__(self):
        self.conectar()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._logado:
                self.logout()
        except Exception:
            pass
        try:
            self.desconectar()
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Conexão e sessão
    # ------------------------------------------------------------------
    def conectar(self) -> None:
        """Carrega a DLL e detecta slots com token."""
        logger.info("A carregar biblioteca PKCS#11...")
        self._pkcs11 = PyKCS11Lib()
        self._pkcs11.load(self._dll_path)

        slots = self._pkcs11.getSlotList(tokenPresent=True)
        if not slots:
            raise TokenAusente(
                "Nenhum token encontrado. Verifique se o Token A3 está conectado."
            )

        self._slot = slots[0]
        info = self._pkcs11.getTokenInfo(self._slot)
        logger.info(
            "Token encontrado: %s (slot %d)",
            info.label.strip(),
            self._slot,
        )

    def desconectar(self) -> None:
        """Libera a biblioteca PKCS#11."""
        if self._pkcs11:
            try:
                self._pkcs11.lib.C_Finalize(0)
            except Exception:
                pass
            self._pkcs11 = None
            logger.debug("Biblioteca PKCS#11 descarregada.")

    def login(self, pin: str) -> None:
        """
        Faz login no token com o PIN fornecido.

        Raises:
            PINInvalido: PIN incorreto (com tentativas restantes)
            PINBloqueado: PIN bloqueado
            TokenAusente: Sem token conectado
        """
        if not self._pkcs11 or not self._slot:
            raise TokenAusente("Não há conexão com o token. Chame conectar() primeiro.")

        try:
            self._sessao = self._pkcs11.openSession(self._slot)
            self._sessao.login(pin)
            self._logado = True
            logger.info("Login no token: SUCESSO")

            # Extrair certificado e chave privada
            self._extrair_certificado()
            self._localizar_chave_privada()

        except PyKCS11Error as e:
            erro = str(e)
            logger.error("Erro PKCS#11 no login: %s", erro)

            # Tentar extrair tentativas restantes
            tentativas = None
            if "CKR_PIN" in erro or "0x00000104" in erro:
                try:
                    info = self._pkcs11.getTokenInfo(self._slot)
                    tentativas = getattr(info, "ulRetryCount", None)
                except Exception:
                    pass
                raise PINInvalido(tentativas_restantes=tentativas)

            if "CKR_PIN_LOCKED" in erro or "0x000000A0" in erro:
                raise PINBloqueado(
                    "O PIN do token foi bloqueado. "
                    "Contacte a Autoridade Certificadora."
                )

            raise ErroTokenA3(f"Erro no login: {e}")

    def logout(self) -> None:
        """Faz logout e fecha a sessão."""
        if self._sessao:
            try:
                self._sessao.logout()
                self._sessao.closeSession()
            except Exception:
                pass
            self._sessao = None
            self._logado = False
            logger.info("Logout do token: OK")

    # ------------------------------------------------------------------
    # Extração de certificado e chave
    # ------------------------------------------------------------------
    def _extrair_certificado(self) -> None:
        """Extrai o certificado X.509 do token (formato DER e PEM)."""
        if not self._sessao:
            raise SessaoExpirada("Sessão não disponível.")

        objs = self._sessao.findObjects(
            [(PyKCS11.CKA_CLASS, PyKCS11.CKO_CERTIFICATE)]
        )

        if not objs:
            raise CertificadoNaoEncontrado(
                "Nenhum certificado encontrado no token."
            )

        obj = objs[0]
        der_bytes = bytes(self._sessao.getAttributeValue(
            obj, [PyKCS11.CKA_VALUE]
        )[0])

        self._certificado_der = der_bytes

        cert = x509.load_der_x509_certificate(der_bytes)
        self._certificado_pem = cert.public_bytes(
            serialization.Encoding.PEM
        ).decode("ascii")

        subject = cert.subject.rfc4514_string()
        logger.info("Certificado extraído: %s", subject)

        not_after = (
            cert.not_valid_after_utc
            if hasattr(cert, 'not_valid_after_utc')
            else cert.not_valid_after
        )
        logger.info("Válido até: %s", not_after.strftime("%d/%m/%Y %H:%M"))

    def _localizar_chave_privada(self) -> None:
        """Localiza a chave privada com capacidade de assinatura."""
        if not self._sessao:
            raise SessaoExpirada("Sessão não disponível.")

        objs = self._sessao.findObjects(
            [(PyKCS11.CKA_CLASS, PyKCS11.CKO_PRIVATE_KEY)]
        )

        for obj in objs:
            try:
                attrs = self._sessao.getAttributeValue(
                    obj, [PyKCS11.CKA_SIGN]
                )
                pode_assinar = bool(attrs[0])
                if pode_assinar:
                    self._chave_privada = obj
                    logger.info("Chave privada de assinatura localizada.")
                    return
            except Exception:
                continue

        raise ChavePrivadaNaoEncontrada(
            "Nenhuma chave privada com capacidade de assinatura encontrada no token."
        )

    # ------------------------------------------------------------------
    # Operações públicas
    # ------------------------------------------------------------------
    def obter_certificado_pem(self) -> str:
        """Retorna o certificado X.509 em formato PEM."""
        if not self._certificado_pem:
            raise CertificadoNaoEncontrado("Certificado não extraído. Faça login primeiro.")
        return self._certificado_pem

    def obter_certificado_der(self) -> bytes:
        """Retorna o certificado X.509 em formato DER."""
        if not self._certificado_der:
            raise CertificadoNaoEncontrado("Certificado não extraído. Faça login primeiro.")
        return self._certificado_der

    def obter_info_certificado(self) -> dict:
        """Retorna informações do certificado."""
        if not self._certificado_der:
            raise CertificadoNaoEncontrado("Certificado não extraído.")

        cert = x509.load_der_x509_certificate(self._certificado_der)
        not_after = (
            cert.not_valid_after_utc
            if hasattr(cert, 'not_valid_after_utc')
            else cert.not_valid_after
        )
        not_before = (
            cert.not_valid_before_utc
            if hasattr(cert, 'not_valid_before_utc')
            else cert.not_valid_before
        )

        return {
            "subject": cert.subject.rfc4514_string(),
            "issuer": cert.issuer.rfc4514_string(),
            "serial": format(cert.serial_number, "X"),
            "valido_de": not_before.strftime("%d/%m/%Y %H:%M"),
            "valido_ate": not_after.strftime("%d/%m/%Y %H:%M"),
            "algoritmo": cert.signature_algorithm_oid._name,
        }

    def assinar(self, dados: bytes) -> bytes:
        """
        Assina dados usando a chave privada do token.

        Usa o mecanismo SHA256-RSA-PKCS (CKM_SHA256_RSA_PKCS).
        O hash é calculado internamente pelo token.

        Parâmetros:
            dados: bytes a assinar

        Retorna:
            bytes da assinatura digital

        Raises:
            ErroAssinatura: Se a operação falhar
        """
        if not self._sessao or not self._chave_privada:
            raise ErroTokenA3(
                "Sessão ou chave privada não disponível. Faça login primeiro."
            )

        try:
            mecanismo = PyKCS11.Mechanism(PyKCS11.CKM_SHA256_RSA_PKCS, None)
            assinatura = bytes(self._sessao.sign(
                self._chave_privada, dados, mecanismo
            ))
            logger.info("Assinatura SHA256_RSA_PKCS gerada: %d bytes", len(assinatura))
            return assinatura

        except PyKCS11Error as e:
            logger.warning(
                "CKM_SHA256_RSA_PKCS falhou (%s). Tentando fallback com SHA-256 manual...",
                e,
            )

            import hashlib
            digest = hashlib.sha256(dados).digest()

            try:
                mecanismo = PyKCS11.Mechanism(PyKCS11.CKM_RSA_PKCS, None)
                assinatura = bytes(self._sessao.sign(
                    self._chave_privada, digest, mecanismo
                ))
                logger.info(
                    "Assinatura RSA_PKCS (fallback) gerada: %d bytes",
                    len(assinatura),
                )
                return assinatura
            except PyKCS11Error as e2:
                raise ErroAssinatura(
                    f"Falha na assinatura com ambos mecanismos: {e2}"
                )

    def criar_funcao_assinatura(self) -> Callable[[bytes], bytes]:
        """
        Retorna uma função de assinatura compatível com assinatura_xml.py.

        Uso:
            funcao_assinar = token.criar_funcao_assinatura()
            xml_assinado = assinar_xml(xml_bytes, cert_pem, funcao_assinar)
        """
        def _assinar(dados: bytes) -> bytes:
            return self.assinar(dados)
        return _assinar

    def listar_slots(self) -> List[dict]:
        """Lista todos os slots disponíveis (com e sem token)."""
        if not self._pkcs11:
            raise ErroTokenA3("Biblioteca não carregada. Chame conectar() primeiro.")

        slots_info = []
        all_slots = self._pkcs11.getSlotList()

        for slot in all_slots:
            try:
                info = self._pkcs11.getTokenInfo(slot)
                slots_info.append({
                    "slot_id": slot,
                    "label": info.label.strip(),
                    "manufacturer": info.manufacturerID.strip(),
                    "serial": info.serialNumber.strip(),
                    "present": True,
                })
            except PyKCS11Error:
                slots_info.append({
                    "slot_id": slot,
                    "label": "(vazio)",
                    "manufacturer": "",
                    "serial": "",
                    "present": False,
                })

        return slots_info
