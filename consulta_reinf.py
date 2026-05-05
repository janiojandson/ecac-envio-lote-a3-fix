"""
consulta_reinf.py — Consulta de Protocolos EFD-REINF
=====================================================
Lê protocolos pendentes, consulta o endpoint da Receita,
guarda recibos e remove protocolos concluídos.

Adaptado do código original do Dutra Gomes.
"""

import argparse
import glob
import logging
import os
import sys
import time
from pathlib import Path

import requests
from lxml import etree

from config import (
    AMBIENTES,
    HTTP_TIMEOUT,
    PASTA_PROTOCOLOS,
    PASTA_RECIBOS,
)

logger = logging.getLogger(__name__)

# Namespace do retorno REINF
NS_REINF = {
    "ns": "http://www.reinf.esocial.gov.br/schemas/retornoLoteEventosAssincrono/v1_00_00"
}


def consultar_protocolo(protocolo: str, url_base: str, sessao: requests.Session) -> dict:
    """
    Consulta um protocolo específico na Receita Federal.

    Retorna dict com:
        - status: 'concluido' | 'processando' | 'erro'
        - codigo: código de resposta da Receita
        - conteudo: XML de resposta (bytes) se concluído
        - mensagem: descrição do resultado
    """
    url = f"{url_base}{protocolo}"
    logger.info("Consultando protocolo: %s", protocolo)
    logger.debug("URL: %s", url)

    headers = {
        "Accept": "application/xml",
        "User-Agent": "EFD-REINF-Consulta/1.0",
    }

    try:
        response = sessao.get(url, headers=headers, timeout=HTTP_TIMEOUT)

        if response.status_code == 200:
            try:
                root = etree.fromstring(response.content)
                cd_resposta_list = root.xpath("//ns:cdResposta", namespaces=NS_REINF)

                if not cd_resposta_list:
                    logger.warning(
                        "Resposta sem cdResposta para protocolo %s", protocolo
                    )
                    return {
                        "status": "erro",
                        "codigo": None,
                        "conteudo": None,
                        "mensagem": "Resposta sem cdResposta",
                    }

                cd_resposta = cd_resposta_list[0].text.strip()

                if cd_resposta == "2":
                    logger.info("Protocolo %s: CONCLUIDO", protocolo)
                    return {
                        "status": "concluido",
                        "codigo": cd_resposta,
                        "conteudo": response.content,
                        "mensagem": "Lote processado com sucesso",
                    }
                elif cd_resposta == "1":
                    logger.info("Protocolo %s: PROCESSANDO", protocolo)
                    return {
                        "status": "processando",
                        "codigo": cd_resposta,
                        "conteudo": None,
                        "mensagem": "Lote ainda em processamento",
                    }
                else:
                    logger.warning(
                        "Protocolo %s: codigo inesperado %s", protocolo, cd_resposta
                    )
                    msg_erro = ""
                    descricao_list = root.xpath("//ns:descRetorno", namespaces=NS_REINF)
                    if descricao_list:
                        msg_erro = descricao_list[0].text or ""

                    return {
                        "status": "erro",
                        "codigo": cd_resposta,
                        "conteudo": response.content,
                        "mensagem": f"Codigo {cd_resposta}: {msg_erro}",
                    }

            except etree.XMLSyntaxError as e:
                logger.error("XML invalido na resposta: %s", e)
                return {
                    "status": "erro",
                    "codigo": None,
                    "conteudo": None,
                    "mensagem": f"XML invalido: {e}",
                }

        elif response.status_code == 404:
            logger.warning("Protocolo %s nao encontrado (404)", protocolo)
            return {
                "status": "erro",
                "codigo": "404",
                "conteudo": None,
                "mensagem": "Protocolo nao encontrado",
            }
        else:
            logger.error(
                "Erro HTTP %d para protocolo %s: %s",
                response.status_code,
                protocolo,
                response.text[:200],
            )
            return {
                "status": "erro",
                "codigo": str(response.status_code),
                "conteudo": None,
                "mensagem": f"HTTP {response.status_code}",
            }

    except requests.exceptions.Timeout:
        logger.error("Timeout ao consultar protocolo %s", protocolo)
        return {
            "status": "erro",
            "codigo": None,
            "conteudo": None,
            "mensagem": "Timeout na consulta",
        }
    except requests.exceptions.ConnectionError as e:
        logger.error("Erro de conexao: %s", e)
        return {
            "status": "erro",
            "codigo": None,
            "conteudo": None,
            "mensagem": f"Erro de conexao: {e}",
        }


def consultar_todos_protocolos(ambiente: str = "producao") -> None:
    """
    Consulta todos os protocolos pendentes na pasta /protocolos.
    """
    url_base = AMBIENTES[ambiente]["consulta"]
    logger.info("=== Consulta de Protocolos EFD-REINF ===")
    logger.info("Ambiente: %s", ambiente)
    logger.info("URL base: %s", url_base)
    logger.info("Pasta de protocolos: %s", PASTA_PROTOCOLOS)

    # Buscar protocolos pendentes
    arquivos = sorted(glob.glob(os.path.join(str(PASTA_PROTOCOLOS), "*.txt")))

    if not arquivos:
        logger.info("Nenhum protocolo pendente para consulta.")
        print("Nenhum protocolo pendente para consulta.")
        return

    logger.info("Encontrados %d protocolos pendentes.", len(arquivos))
    print(f"\nEncontrados {len(arquivos)} protocolos pendentes.\n")

    # Usar sessão para reutilizar conexão TLS
    sessao = requests.Session()

    # Estatísticas
    stats = {"concluido": 0, "processando": 0, "erro": 0}

    for arquivo_path in arquivos:
        nome_arquivo = os.path.basename(arquivo_path)

        try:
            with open(arquivo_path, "r", encoding="utf-8") as f:
                protocolo = f.read().strip()

            if not protocolo:
                logger.warning("Arquivo %s esta vazio. Ignorando.", nome_arquivo)
                continue

            resultado = consultar_protocolo(protocolo, url_base, sessao)
            stats[resultado["status"]] += 1

            if resultado["status"] == "concluido":
                # Guardar recibo
                nome_recibo = (
                    nome_arquivo.replace(".txt", ".xml").replace("PROT_", "RECIBO_")
                )
                caminho_recibo = PASTA_RECIBOS / nome_recibo

                with open(caminho_recibo, "wb") as f_rec:
                    f_rec.write(resultado["conteudo"])

                logger.info("Recibo salvo: %s", caminho_recibo)
                print(f"  OK {protocolo} -> CONCLUIDO | Recibo: {nome_recibo}")

                # Remover protocolo concluído
                os.remove(arquivo_path)
                logger.debug("Protocolo removido: %s", arquivo_path)

            elif resultado["status"] == "processando":
                print(f"  WAIT {protocolo} -> Ainda processando...")

            else:
                print(f"  X {protocolo} -> ERRO: {resultado['mensagem']}")

        except Exception as e:
            logger.error("Erro ao processar %s: %s", nome_arquivo, e)
            print(f"  X {nome_arquivo} -> ERRO: {e}")
            stats["erro"] += 1

        # Pausa entre consultas
        time.sleep(1)

    # Resumo
    print(f"\n{'='*50}")
    print(f"RESUMO DA CONSULTA:")
    print(f"  Concluidos:  {stats['concluido']}")
    print(f"  Processando: {stats['processando']}")
    print(f"  Erros:       {stats['erro']}")
    print(f"  Total:       {sum(stats.values())}")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Consulta protocolos pendentes na EFD-REINF"
    )
    parser.add_argument(
        "--ambiente",
        choices=["producao", "homologacao"],
        default="producao",
        help="Ambiente de consulta (padrao: producao)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Modo verboso (DEBUG)",
    )

    args = parser.parse_args()

    # Configurar logging
    nivel = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    consultar_todos_protocolos(ambiente=args.ambiente)


if __name__ == "__main__":
    main()
