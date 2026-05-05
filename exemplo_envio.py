"""
exemplo_envio.py — Exemplo de uso completo do sistema
======================================================
Demonstra como:
  1. Criar um XML de evento R-4020 básico
  2. Conectar ao Token A3
  3. Assinar e transmitir

NOTA: Este é um EXEMPLO EDUCATIVO. Em produção, os XMLs
devem ser gerados pelo seu sistema de folha de pagamento.
"""

import sys
from datetime import datetime
from getpass import getpass
from pathlib import Path

from lxml import etree

# Namespace do REINF
REINF_NS = "http://www.reinf.esocial.gov.br/schemas/evt4020PagtoBeneficiarioPJ/v2_01_00"
NSMAP = {None: REINF_NS}


def criar_xml_exemplo_r4020() -> bytes:
    """
    Cria um XML de evento R-4020 (Pagamento a Beneficiário PJ) de exemplo.
    ATENÇÃO: Este XML é apenas para teste. Substitua os dados reais.
    """
    agora = datetime.now()

    evt = etree.Element(
        f"{{{REINF_NS}}}evt4020PagtoBeneficiarioPJ",
        nsmap=NSMAP,
    )
    evt.set("id", f"ID12345678900000{agora:%Y%m%d%H%M%S}00001")

    # IdeEvento
    ide_evt = etree.SubElement(evt, "ideEvento")
    etree.SubElement(ide_evt, "tpAmb").text = "2"  # 1=Produção, 2=Homologação
    etree.SubElement(ide_evt, "procEmi").text = "1"  # 1=Aplicativo do contribuinte
    etree.SubElement(ide_evt, "verProc").text = "1.0.0"

    # IdeContri (contribuinte)
    ide_contri = etree.SubElement(evt, "ideContri")
    etree.SubElement(ide_contri, "tpInsc").text = "1"  # 1=CNPJ
    etree.SubElement(ide_contri, "nrInsc").text = "00000000000100"  # CNPJ fictício

    # ideBenef (beneficiário)
    ide_benef = etree.SubElement(evt, "ideBenef")
    etree.SubElement(ide_benef, "cnpjBenef").text = "00000000000191"

    # idePgto
    ide_pgto = etree.SubElement(ide_benef, "idePgto")
    etree.SubElement(ide_pgto, "natRend").text = "12345"

    # infoPgto
    info_pgto = etree.SubElement(ide_pgto, "infoPgto")
    etree.SubElement(info_pgto, "dtPgto").text = f"{agora:%Y-%m-%d}"
    etree.SubElement(info_pgto, "vlrBruto").text = "10000.00"
    etree.SubElement(info_pgto, "vlrBaseIR").text = "10000.00"
    etree.SubElement(info_pgto, "vlrIR").text = "1500.00"

    xml_bytes = etree.tostring(
        evt,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
        pretty_print=True,
    )

    return xml_bytes


def main():
    print("=" * 60)
    print("EXEMPLO: Envio de Evento R-4020 com Token A3")
    print("=" * 60)

    # 1. Criar XML de exemplo
    print("\nCriando XML de evento R-4020 de exemplo...")
    xml_bytes = criar_xml_exemplo_r4020()

    # Guardar na pasta de envios
    pasta_envios = Path("envios")
    pasta_envios.mkdir(exist_ok=True)

    nome_arquivo = f"LOTE_R4020_EXEMPLO_{datetime.now():%Y%m%d_%H%M%S}.xml"
    caminho = pasta_envios / nome_arquivo

    with open(caminho, "wb") as f:
        f.write(xml_bytes)

    print(f"XML guardado: {caminho}")
    print(f"   Tamanho: {len(xml_bytes)} bytes")

    # 2. Mostrar o XML gerado
    print("\nConteudo do XML:")
    print("-" * 40)
    print(xml_bytes.decode("utf-8"))
    print("-" * 40)

    # 3. Perguntar se quer transmitir
    print("\nATENCAO: Este e um XML de EXEMPLO com dados ficticios.")
    print("   NAO transmita para a Receita Federal com dados falsos!")
    print("   Use este codigo apenas como referencia para o seu XML real.\n")

    resposta = input("Deseja mesmo assim executar a transmissao? (s/N): ")
    if resposta.lower() != "s":
        print("Operacao cancelada. O XML foi guardado em:", caminho)
        print("Para transmitir manualmente:")
        print(f"  python transmissao_a3.py --pin SEU_PIN")
        return

    # 4. Obter PIN e transmitir
    pin = getpass("PIN do Token A3: ")
    if not pin:
        print("PIN e obrigatorio.")
        return

    from transmissao_a3 import executar_transmissao
    executar_transmissao(pin=pin, ambiente="homologacao")


if __name__ == "__main__":
    main()
