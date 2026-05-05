"""
transmissao_a3.py — Transmissão de Lotes EFD-REINF com Token A3
================================================================
Script principal que:
  1. Conecta ao Token A3 via PKCS#11
  2. Carrega XMLs da pasta /envios
  3. Assina cada XML com o certificado do token
  4. Transmite via POST para a Receita Federal
  5. Guarda protocolos em /protocolos
  6. Move XMLs transmitidos para /recebidos

Substitui o modelo antigo (requests + pip-system-certs) que causava
o Erro 496 (Certificado de Cliente Ausente).

Uso:
    python transmissao_a3.py --pin 123456
    python transmissao_a3.py --pin 123456 --ambiente homologacao
    python transmissao_a3.py  # (pede o PIN interactivamente)
"""

import argparse
import glob
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from getpass import getpass
from pathlib import Path

import requests

from config import (
    AMBIENTES,
    HTTP_INTERVALO_TENTATIVA,
    HTTP_MAX_TENTATIVAS,
    HTTP_TIMEOUT,
    LOG_FORMATO,
    LOG_NIVEL,
    PASTA_ENVIOS,
    PASTA_PROTOCOLOS,
    PASTA_RECEBIDOS,
    PKCS11_DLL_PATH,
)
from certificado_a3 import TokenA3Manager, ErroTokenA3
from assinatura_xml import assinar_xml, verificar_assinatura

logger = logging.getLogger("transmissao")


def configurar_logging(verbose: bool = False) -> None:
    """Configura o sistema de logging."""
    nivel = logging.DEBUG if verbose else getattr(logging, LOG_NIVEL, logging.INFO)

    # Console
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(nivel)
    console.setFormatter(logging.Formatter(LOG_FORMATO))

    # Ficheiro de log
    from config import PASTA_LOGS
    log_file = PASTA_LOGS / f"transmissao_{datetime.now():%Y%m%d_%H%M%S}.log"
    ficheiro = logging.FileHandler(str(log_file), encoding="utf-8")
    ficheiro.setLevel(logging.DEBUG)
    ficheiro.setFormatter(logging.Formatter(LOG_FORMATO))

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console)
    root_logger.addHandler(ficheiro)

    logger.info("Logs guardados em: %s", log_file)


def listar_xmls_para_envio(pasta: Path) -> list:
    """Lista todos os XMLs na pasta de envios."""
    xmls = sorted(glob.glob(os.path.join(str(pasta), "*.xml")))
    logger.info("Encontrados %d XMLs em %s", len(xmls), pasta)
    return xmls


def transmitir_lote(
    xml_assinado: bytes,
    url: str,
    nome_arquivo: str,
    sessao: requests.Session,
) -> dict:
    """
    Transmite um XML assinado para a Receita Federal.

    Retorna dict com:
        - sucesso: bool
        - status_code: int
        - protocolo: str ou None
        - resposta: str
    """
    headers = {
        "Content-Type": "application/xml",
        "Accept": "application/xml",
        "User-Agent": "EFD-REINF-Transmissao-A3/1.0",
    }

    for tentativa in range(1, HTTP_MAX_TENTATIVAS + 1):
        try:
            logger.info(
                "Tentativa %d/%d — Enviando %s (%d bytes)...",
                tentativa,
                HTTP_MAX_TENTATIVAS,
                nome_arquivo,
                len(xml_assinado),
            )

            response = sessao.post(
                url,
                data=xml_assinado,
                headers=headers,
                timeout=HTTP_TIMEOUT,
            )

            if response.status_code in (200, 201):
                # Extrair protocolo da resposta
                protocolo = None
                try:
                    from lxml import etree
                    root = etree.fromstring(response.content)
                    ns = {
                        "ns": "http://www.reinf.esocial.gov.br/schemas/retornoLoteEventosAssincrono/v1_00_00"
                    }
                    prot_list = root.xpath("//ns:protocoloEnvio", namespaces=ns)
                    if prot_list:
                        protocolo = prot_list[0].text
                except Exception:
                    pass

                logger.info(
                    "SUCESSO: %s | Protocolo: %s",
                    nome_arquivo,
                    protocolo or "(não extraído)",
                )
                return {
                    "sucesso": True,
                    "status_code": response.status_code,
                    "protocolo": protocolo,
                    "resposta": response.text,
                }
            else:
                logger.warning(
                    "HTTP %d: %s — %s",
                    response.status_code,
                    nome_arquivo,
                    response.text[:300],
                )

                # Se for erro do lado do cliente (4xx), não retentar
                if 400 <= response.status_code < 500:
                    return {
                        "sucesso": False,
                        "status_code": response.status_code,
                        "protocolo": None,
                        "resposta": response.text,
                    }

        except requests.exceptions.Timeout:
            logger.warning("Timeout na tentativa %d", tentativa)
        except requests.exceptions.ConnectionError as e:
            logger.warning("Erro de conexão na tentativa %d: %s", tentativa, e)
        except Exception as e:
            logger.error("Erro inesperado: %s", e)
            return {
                "sucesso": False,
                "status_code": 0,
                "protocolo": None,
                "resposta": str(e),
            }

        if tentativa < HTTP_MAX_TENTATIVAS:
            logger.info("Aguardando %ds antes da próxima tentativa...", HTTP_INTERVALO_TENTATIVA)
            time.sleep(HTTP_INTERVALO_TENTATIVA)

    return {
        "sucesso": False,
        "status_code": 0,
        "protocolo": None,
        "resposta": "Todas as tentativas falharam",
    }


def salvar_protocolo(nome_arquivo: str, protocolo: str) -> Path:
    """Salva o protocolo em /protocolos."""
    nome_prot = nome_arquivo.replace(".xml", ".txt").replace("LOTE_", "PROT_")
    caminho = PASTA_PROTOCOLOS / nome_prot
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(protocolo)
    logger.info("Protocolo salvo: %s", caminho)
    return caminho


def mover_para_recebidos(nome_arquivo: str) -> Path:
    """Move o XML de /envios para /recebidos."""
    origem = PASTA_ENVIOS / nome_arquivo
    destino = PASTA_RECEBIDOS / nome_arquivo
    shutil.move(str(origem), str(destino))
    logger.info("Movido para recebidos: %s", destino)
    return destino


def executar_transmissao(
    pin: str,
    ambiente: str = "producao",
    dll_path: str = None,
    pasta_envios: Path = None,
) -> None:
    """
    Função principal de transmissão.

    Fluxo:
      1. Conectar ao Token A3
      2. Login com PIN
      3. Para cada XML: assinar → transmitir → guardar protocolo
      4. Logout e desconectar
    """
    pasta = pasta_envios or PASTA_ENVIOS
    url_recepcao = AMBIENTES[ambiente]["recepcao"]

    logger.info("=" * 60)
    logger.info("TRANSMISSÃO EFD-REINF COM TOKEN A3")
    logger.info("=" * 60)
    logger.info("Ambiente: %s", ambiente)
    logger.info("URL: %s", url_recepcao)
    logger.info("Pasta de envios: %s", pasta)
    logger.info("DLL PKCS#11: %s", dll_path or PKCS11_DLL_PATH)

    # 1. Listar XMLs
    xmls = listar_xmls_para_envio(pasta)
    if not xmls:
        logger.info("Nenhum XML para transmitir. Encerrando.")
        print("\nNenhum XML encontrado na pasta de envios.")
        return

    print(f"\nEncontrados {len(xmls)} XML(s) para transmissão.\n")

    # 2. Conectar ao Token A3
    try:
        with TokenA3Manager(dll_path=dll_path) as token:
            token.login(pin)

            # Mostrar info do certificado
            info_cert = token.obter_info_certificado()
            logger.info("Certificado: %s", info_cert["subject"])
            logger.info("Valido ate: %s", info_cert["valido_ate"])
            print(f"Token conectado: {info_cert['subject']}")
            print(f"   Valido ate: {info_cert['valido_ate']}\n")

            # Preparar função de assinatura
            funcao_assinar = token.criar_funcao_assinatura()
            cert_pem = token.obter_certificado_pem()

            # 3. Processar cada XML
            sessao_http = requests.Session()
            stats = {"sucesso": 0, "erro": 0, "total": len(xmls)}

            for i, xml_path in enumerate(xmls, 1):
                nome = os.path.basename(xml_path)
                logger.info("--- [%d/%d] Processando: %s ---", i, len(xmls), nome)
                print(f"[{i}/{len(xmls)}] {nome}...")

                # Ler XML original
                with open(xml_path, "rb") as f:
                    xml_bytes = f.read()

                # Assinar
                try:
                    logger.info("A assinar XML...")
                    xml_assinado = assinar_xml(xml_bytes, cert_pem, funcao_assinar)

                    # Verificar estrutura da assinatura
                    if not verificar_assinatura(xml_assinado):
                        logger.error("Assinatura inválida para %s", nome)
                        print(f"  X Assinatura inválida!")
                        stats["erro"] += 1
                        continue

                except Exception as e:
                    logger.error("Erro ao assinar %s: %s", nome, e)
                    print(f"  X Erro na assinatura: {e}")
                    stats["erro"] += 1
                    continue

                # Transmitir
                resultado = transmitir_lote(
                    xml_assinado, url_recepcao, nome, sessao_http
                )

                if resultado["sucesso"] and resultado["protocolo"]:
                    salvar_protocolo(nome, resultado["protocolo"])
                    mover_para_recebidos(nome)
                    print(f"  OK Enviado! Protocolo: {resultado['protocolo']}")
                    stats["sucesso"] += 1
                elif resultado["sucesso"]:
                    mover_para_recebidos(nome)
                    print(f"  OK Enviado! (protocolo nao extraido)")
                    stats["sucesso"] += 1
                else:
                    print(f"  X Erro HTTP {resultado['status_code']}: {resultado['resposta'][:200]}")
                    stats["erro"] += 1

                # Pausa entre envios
                if i < len(xmls):
                    time.sleep(1)

            # 4. Resumo final
            print(f"\n{'='*60}")
            print(f"RESUMO DA TRANSMISSAO:")
            print(f"  Sucesso: {stats['sucesso']}")
            print(f"  Erros:   {stats['erro']}")
            print(f"  Total:   {stats['total']}")
            print(f"{'='*60}\n")

    except ErroTokenA3 as e:
        logger.error("Erro no Token A3: %s", e)
        print(f"\nERRO NO TOKEN A3: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error("Erro fatal: %s", e, exc_info=True)
        print(f"\nERRO FATAL: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Transmissão de lotes EFD-REINF com Token A3 (PKCS#11)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python transmissao_a3.py --pin 123456
  python transmissao_a3.py --pin 123456 --ambiente homologacao
  python transmissao_a3.py  # pede o PIN interactivamente
  python transmissao_a3.py --dll "C:\\Windows\\System32\\DXSafePKCS11.dll"
        """,
    )
    parser.add_argument(
        "--pin",
        help="PIN do Token A3 (se omitido, pede interactivamente)",
    )
    parser.add_argument(
        "--ambiente",
        choices=["producao", "homologacao"],
        default="producao",
        help="Ambiente de transmissão (padrão: producao)",
    )
    parser.add_argument(
        "--dll",
        help="Caminho da DLL PKCS#11 (padrão: auto-detecção)",
    )
    parser.add_argument(
        "--pasta",
        help="Pasta com os XMLs para envio (padrão: ./envios)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Modo verboso (DEBUG)",
    )

    args = parser.parse_args()

    # Configurar logging
    configurar_logging(verbose=args.verbose)

    # Obter PIN
    pin = args.pin
    if not pin:
        pin = getpass("Digite o PIN do Token A3: ")

    if not pin:
        print("PIN é obrigatório.")
        sys.exit(1)

    # Executar
    pasta = Path(args.pasta) if args.pasta else None
    executar_transmissao(
        pin=pin,
        ambiente=args.ambiente,
        dll_path=args.dll,
        pasta_envios=pasta,
    )


if __name__ == "__main__":
    main()
