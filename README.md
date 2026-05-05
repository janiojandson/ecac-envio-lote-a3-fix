# Solucao Definitiva — EFD-REINF com Token A3 (PyKCS11)

## O Problema: Erro 496 — Certificado de Cliente Ausente

Se estas a tentar transmitir lotes EFD-REINF (serie R-4020) com um Token A3 (smartcard USB) e recebeste o **Erro 496**, o problema e este:

> O `requests` (Python) usa o OpenSSL por baixo. O OpenSSL **nao consegue extrair a chave privada** protegida pelo driver do Token A3 (ex: `DXSafePKCS11.dll` da AC Defesa). O certificado esta "visivel" no Windows, mas a chave privada fica trancada dentro do hardware do token.

### Porque que `pip-system-certs` nao resolve?

A biblioteca `pip-system-certs` faz o Python usar o repositorio de certificados do Windows (Schannel). Mas o Schannel so consegue usar a chave privada se ela estiver exportavel — e nos tokens A3, **a chave NUNCA e exportavel** por razoes de seguranca.

### A Solucao: PyKCS11

Em vez de tentar "forcar" o OpenSSL ou o Schannel a aceder ao token, usamos o **PyKCS11** — uma biblioteca Python que fala directamente com o driver PKCS#11 do token. Isto permite:

1. Listar slots e detectar o token
2. Fazer login com o PIN
3. Extrair o certificado X.509
4. **Assinar dados directamente dentro do hardware do token**
5. Montar a assinatura XMLDSig no XML
6. Transmitir o XML assinado via HTTPS

---

## Pre-requisitos

### 1. Python 64-bits (OBRIGATORIO!)

Os drivers PKCS#11 dos tokens A3 sao DLLs de 64 bits. Se usares Python 32-bits, vais receber erro de "DLL not found" ou "module not loadable".

**Verificar se o Python e 64-bits:**
```
python -c "import struct; print(struct.calcsize('P') * 8, 'bits')"
```
Deve mostrar: `64 bits`

Se mostrar `32 bits`, desinstala e instala o Python 64-bits de [python.org](https://www.python.org/downloads/).

### 2. Token A3 conectado e com driver instalado

- O token USB deve estar ligado ao computador
- O driver do fabricante deve estar instalado (ex: DXSafe para AC Defesa)
- O certificado deve estar instalado no token (feito pela AC)

### 3. Saber o caminho da DLL PKCS#11

| Fabricante / AC | DLL tipica |
|---|---|
| AC Defesa (Token A3 militar) | `C:\Windows\System32\DXSafePKCS11.dll` |
| SafeNet / eToken | `C:\Windows\System32\eTPKCS11.dll` |
| OpenSC (generico) | `C:\Windows\System32\opensc-pkcs11.dll` |
| ICP-Brasil (alguns tokens) | `C:\Windows\System32\acpkcs211.dll` |
| Watchdata | `C:\Windows\System32\WDPKCS.dll` |
| Certisign | `C:\Windows\System32\SignatureP11.dll` |

**Para verificar se a DLL existe:**
```
dir C:\Windows\System32\DXSafePKCS11.dll
```

---

## Instalacao

### Passo 1: Clonar o repositorio

```
git clone https://github.com/janiojandson/ecac-envio-lote-a3-fix.git
cd ecac-envio-lote-a3-fix
```

### Passo 2: Criar ambiente virtual (recomendado)

```
python -m venv venv
venv\Scripts\activate
```

### Passo 3: Instalar dependencias

```
pip install -r requirements.txt
```

**Se o PyKCS11 falhar a compilar**, instala o Visual C++ Build Tools:
```
pip install --upgrade pip setuptools wheel
pip install PyKCS11
```

### Passo 4: Verificar instalacao

```
python -c "import PyKCS11; print('PyKCS11 OK:', PyKCS11.__version__)"
python -c "from cryptography import x509; print('cryptography OK')"
python -c "from lxml import etree; print('lxml OK')"
```

---

## Estrutura do Projecto

```
ecac-envio-lote-a3-fix/
│
├── config.py              # Configuracoes centralizadas (URLs, caminhos, timeouts)
├── certificado_a3.py      # Gestao do Token A3 via PKCS#11
├── assinatura_xml.py      # Assinatura XML digital (XMLDSig)
├── transmissao_a3.py      # Script principal de transmissao
├── consulta_reinf.py      # Consulta de protocolos pendentes
├── exemplo_envio.py       # Exemplo completo de uso
├── requirements.txt       # Dependencias Python
├── README.md              # Este ficheiro
│
├── envios/                # Coloca aqui os XMLs para transmitir
├── recebidos/             # XMLs transmitidos com sucesso
├── protocolos/            # Protocolos de envio (para consulta posterior)
├── recibos/               # Recibos definitivos da Receita
└── logs/                  # Logs detalhados de cada execucao
```

---

## Como Usar

### Transmissao de Lotes

**Modo interactivo (pede o PIN):**
```
python transmissao_a3.py
```

**Com PIN via argumento:**
```
python transmissao_a3.py --pin 123456
```

**Ambiente de homologacao (testes):**
```
python transmissao_a3.py --pin 123456 --ambiente homologacao
```

**Especificar a DLL manualmente:**
```
python transmissao_a3.py --pin 123456 --dll "C:\Windows\System32\DXSafePKCS11.dll"
```

**Modo verboso (debug):**
```
python transmissao_a3.py --pin 123456 --verbose
```

### Consulta de Protocolos

Depois de transmitir, consulta se os lotes foram processados:

```
python consulta_reinf.py
python consulta_reinf.py --ambiente homologacao
python consulta_reinf.py --verbose
```

### Exemplo Completo

Para testar com um XML de exemplo (R-4020 ficticio):

```
python exemplo_envio.py
```

---

## Fluxo de Trabalho

```
1. Gerar XMLs do R-4020 (pelo teu sistema de folha)
   -> Colocar na pasta /envios

2. python transmissao_a3.py --pin SEU_PIN
   -> Conecta ao Token A3
   -> Extrai o certificado
   -> Assina cada XML (XMLDSig enveloped)
   -> Transmite via POST para a Receita
   -> Guarda protocolos em /protocolos
   -> Move XMLs para /recebidos

3. python consulta_reinf.py
   -> Consulta protocolos pendentes
   -> Guarda recibos em /recibos
   -> Remove protocolos concluidos
```

---

## Troubleshooting

### "BibliotecaPKCS11NaoEncontrada: Nenhuma biblioteca PKCS#11 encontrada"

- Verifica se o driver do token esta instalado
- Verifica se a DLL existe: `dir C:\Windows\System32\DXSafePKCS11.dll`
- Define a variavel de ambiente: `set PKCS11_MODULE_PATH=C:\Windows\System32\DXSafePKCS11.dll`
- Ou usa o argumento `--dll`

### "TokenAusente: Nenhum token encontrado"

- Verifica se o token USB esta ligado
- Tenta remover e voltar a inserir o token
- Verifica se o driver esta correctamente instalado

### "PINInvalido: PIN incorreto"

- O PIN do Token A3 e numerico (geralmente 4-8 digitos)
- Cuidado: apos 3 tentativas erradas, o PIN pode bloquear!
- Se bloquear, contacta a Autoridade Certificadora

### "O Python nao encontra o PyKCS11"

- Verifica se estas a usar o Python correcto: `where python`
- Verifica se o ambiente virtual esta activo: `venv\Scripts\activate`
- Reinstala: `pip install --force-reinstall PyKCS11`

### "Erro de SSL ao transmitir"

- Verifica se tem ligacao a internet
- Verifica se o firewall nao bloqueia HTTPS para `reinf.receita.economia.gov.br`
- Tenta com `--verbose` para ver detalhes do erro

### "Python 32 bits nao encontra a DLL"

- **Solucao:** Instala o Python 64-bits!
- Os drivers PKCS#11 dos tokens A3 sao sempre 64-bits no Windows moderno

### "O certificado esta expirado"

- Verifica a validade: o script mostra "Valido ate" ao iniciar
- Contacta a AC para renovar o certificado

---

## Arquitectura Tecnica

### Porque PyKCS11 e nao requests + cert PEM?

| Abordagem | Resultado |
|---|---|
| `requests.get(url, cert="cert.pem")` | Erro 496 — OpenSSL nao acede a chave privada do token |
| `pip-system-certs` + Schannel | Schannel so funciona com chaves exportaveis |
| `PyKCS11` -> assinar -> transmitir | Acesso directo ao token via driver PKCS#11 |

### Fluxo de Assinatura XMLDSig

```
XML Original
    |
    v
1. Canonicalizar (C14N)
2. Calcular SHA-256 digest
    |
    v
3. Criar <ds:SignedInfo>
   - CanonicalizationMethod
   - SignatureMethod (RSA)
   - Reference + DigestValue
    |
    v
4. Canonicalizar SignedInfo
5. Assinar com Token A3        <-- AQUI o token faz a assinatura
   (CKM_SHA256_RSA_PKCS)          com a chave privada protegida
    |
    v
6. Montar <ds:Signature>
   - SignedInfo
   - SignatureValue
   - KeyInfo (X509Certificate)
7. Inserir no XML
    |
    v
XML Assinado -> POST para Receita Federal
```

---

## Suporte

Este projecto foi desenvolvido para resolver o problema especifico do Erro 496 com Token A3 na transmissao de lotes EFD-REINF.

**Autor:** Janio Jandson (janiojandson)
**Colaborador:** Dutra Gomes
**Repositorio original:** [jdutrag/ecac-envio_lote](https://github.com/jdutrag/ecac-envio_lote)

---

## Licenca

Codigo livre para uso interno. Adaptado conforme necessario para a realidade da tua organizacao.
