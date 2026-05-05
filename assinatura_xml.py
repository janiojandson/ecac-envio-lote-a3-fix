"""
assinatura_xml.py — Assinatura XML Digital (XMLDSig) para EFD-REINF
====================================================================
Assina XMLs de eventos REINF usando o certificado do Token A3.
Padrão: XMLDSig Enveloped Signature com SHA-256 + RSA.
"""

import base64
import hashlib
import logging
import re
from copy import deepcopy
from typing import Optional, Tuple

from lxml import etree

from config import (
    XML_ALGORITHM_SHA256,
    XML_CANONICALIZATION,
    XML_SIGNATURE_METHOD,
    XML_TRANSFORM_ENVELOPED,
)

logger = logging.getLogger(__name__)

# Namespace da assinatura XML
DS_NS = "http://www.w3.org/2000/09/xmldsig#"
NSMAP_DS = {"ds": DS_NS}

# Regex para limpar XML antes de canonicalizar
RE_XML_DECL = re.compile(rb"<\?xml[^?]*\?>\s*")


def _canonicalize_c14n_exclusive(xml_bytes: bytes) -> bytes:
    """
    Canonicalização C14N Exclusive de um fragmento XML.
    Usa lxml para fazer a serialização canónica.
    """
    xml_limpo = RE_XML_DECL.sub(b"", xml_bytes, count=1)
    try:
        doc = etree.fromstring(xml_limpo)
        return etree.tostring(doc, method="c14n", exclusive=True)
    except etree.XMLSyntaxError:
        return xml_limpo


def _calcular_digest(xml_canon: bytes) -> str:
    """Calcula SHA-256 digest e retorna em Base64."""
    sha256 = hashlib.sha256(xml_canon).digest()
    return base64.b64encode(sha256).decode("ascii")


def _extrair_certificado_base64(certificado_pem: str) -> str:
    """
    Extrai o conteúdo Base64 do certificado PEM (sem headers/footers).
    """
    linhas = certificado_pem.strip().split("\n")
    b64_lines = [
        l for l in linhas
        if not l.startswith("-----BEGIN") and not l.startswith("-----END") and l.strip()
    ]
    return "".join(b64_lines)


def _criar_elemento_signed_info(certificado_pem: str) -> Tuple[etree._Element, bytes]:
    """
    Cria o elemento <ds:SignedInfo> com as referências necessárias.

    Retorna (elemento SignedInfo, bytes canonizados para assinatura).
    """
    signed_info = etree.SubElement(
        etree.Element("dummy"),
        f"{{{DS_NS}}}SignedInfo",
        nsmap=NSMAP_DS,
    )

    # CanonicalizationMethod
    canon_method = etree.SubElement(signed_info, f"{{{DS_NS}}}CanonicalizationMethod")
    canon_method.set("Algorithm", XML_CANONICALIZATION)

    # SignatureMethod
    sig_method = etree.SubElement(signed_info, f"{{{DS_NS}}}SignatureMethod")
    sig_method.set("Algorithm", XML_SIGNATURE_METHOD)

    # Reference (enveloped — aponta para "")
    reference = etree.SubElement(signed_info, f"{{{DS_NS}}}Reference")
    reference.set("URI", "")

    # Transforms
    transforms = etree.SubElement(reference, f"{{{DS_NS}}}Transforms")

    # Transform 1: Enveloped Signature
    transform1 = etree.SubElement(transforms, f"{{{DS_NS}}}Transform")
    transform1.set("Algorithm", XML_TRANSFORM_ENVELOPED)

    # Transform 2: C14N Exclusive
    transform2 = etree.SubElement(transforms, f"{{{DS_NS}}}Transform")
    transform2.set("Algorithm", XML_CANONICALIZATION)

    # DigestMethod
    digest_method = etree.SubElement(reference, f"{{{DS_NS}}}DigestMethod")
    digest_method.set("Algorithm", XML_ALGORITHM_SHA256)

    # DigestValue (placeholder — será preenchido depois)
    digest_value = etree.SubElement(reference, f"{{{DS_NS}}}DigestValue")
    digest_value.text = "PLACEHOLDER"

    # Canonicalizar o SignedInfo (sem o digest ainda)
    signed_info_bytes = etree.tostring(signed_info, method="c14n", exclusive=True)

    return signed_info, signed_info_bytes


def assinar_xml(xml_bytes: bytes, certificado_pem: str, funcao_assinar) -> bytes:
    """
    Assina um XML de evento REINF usando XMLDSig Enveloped Signature.

    Parâmetros:
        xml_bytes: XML original em bytes
        certificado_pem: Certificado X.509 em formato PEM
        funcao_assinar: Callable que recebe (dados: bytes) -> bytes assinados
                        (usa a chave privada do Token A3)

    Retorna:
        XML assinado em bytes, com o elemento <ds:Signature> inserido.
    """
    logger.info("Iniciando assinatura XML digital...")

    # 1. Parse do XML original
    try:
        raiz = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"XML inválido: {e}")

    # 2. Criar SignedInfo com placeholder de digest
    signed_info, signed_info_bytes = _criar_elemento_signed_info(certificado_pem)

    # 3. Calcular digest do documento (enveloped — sem a assinatura ainda)
    doc_canon = _canonicalize_c14n_exclusive(xml_bytes)
    digest_doc = _calcular_digest(doc_canon)
    logger.debug("Digest do documento: %s", digest_doc[:32] + "...")

    # 4. Actualizar DigestValue no SignedInfo
    for ref in signed_info.findall(f"{{{DS_NS}}}Reference"):
        for dv in ref.findall(f"{{{DS_NS}}}DigestValue"):
            dv.text = digest_doc

    # 5. Re-canonicalizar SignedInfo com o digest correcto
    signed_info_bytes = etree.tostring(signed_info, method="c14n", exclusive=True)

    # 6. Assinar o SignedInfo com a chave privada do token
    logger.info("Assinando com chave privada do Token A3...")
    assinatura_bytes = funcao_assinar(signed_info_bytes)
    assinatura_b64 = base64.b64encode(assinatura_bytes).decode("ascii")
    logger.debug("Assinatura gerada: %s bytes", len(assinatura_bytes))

    # 7. Construir o elemento <ds:Signature>
    signature = etree.Element(f"{{{DS_NS}}}Signature", nsmap=NSMAP_DS)
    signature.set("Id", "Signature")

    # 7a. SignedInfo (reparse)
    signed_info_final = deepcopy(signed_info)
    signature.append(signed_info_final)

    # 7b. SignatureValue
    sig_value = etree.SubElement(signature, f"{{{DS_NS}}}SignatureValue")
    sig_value.text = assinatura_b64

    # 7c. KeyInfo com X509Data
    key_info = etree.SubElement(signature, f"{{{DS_NS}}}KeyInfo")
    x509_data = etree.SubElement(key_info, f"{{{DS_NS}}}X509Data")
    x509_cert = etree.SubElement(x509_data, f"{{{DS_NS}}}X509Certificate")
    x509_cert.text = _extrair_certificado_base64(certificado_pem)

    # 8. Inserir a assinatura no XML
    raiz.append(signature)

    # 9. Serializar resultado
    resultado = etree.tostring(
        raiz,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )

    logger.info("XML assinado com sucesso. Tamanho: %d bytes", len(resultado))
    return resultado


def verificar_assinatura(xml_assinado: bytes) -> bool:
    """
    Verifica se o XML contém uma assinatura XMLDSig válida (estrutural).
    NOTA: Não valida criptograficamente — apenas verifica a estrutura.
    """
    try:
        raiz = etree.fromstring(xml_assinado)
        signatures = raiz.findall(f".//{{{DS_NS}}}Signature")
        if not signatures:
            logger.warning("Nenhum elemento <ds:Signature> encontrado no XML.")
            return False

        for sig in signatures:
            si = sig.find(f"{{{DS_NS}}}SignedInfo")
            sv = sig.find(f"{{{DS_NS}}}SignatureValue")
            ki = sig.find(f"{{{DS_NS}}}KeyInfo")

            if si is None or sv is None or ki is None:
                logger.warning("Assinatura incompleta: faltam sub-elementos.")
                return False

            refs = si.findall(f"{{{DS_NS}}}Reference")
            if not refs:
                logger.warning("SignedInfo sem Reference.")
                return False

            for ref in refs:
                dv = ref.find(f"{{{DS_NS}}}DigestValue")
                if dv is None or not dv.text or dv.text == "PLACEHOLDER":
                    logger.warning("DigestValue ausente ou é placeholder.")
                    return False

            cert = ki.find(f".//{{{DS_NS}}}X509Certificate")
            if cert is None or not cert.text:
                logger.warning("X509Certificate ausente no KeyInfo.")
                return False

        logger.info("Estrutura da assinatura XMLDSig verificada: OK")
        return True

    except Exception as e:
        logger.error("Erro ao verificar assinatura: %s", e)
        return False
