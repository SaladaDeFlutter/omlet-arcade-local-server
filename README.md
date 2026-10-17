# Omlet Arcade — Servidor Local (Estudo / Preservação)

Backend local e kit de patch do cliente para o **Omlet Arcade 1.111.9** (pacote
`mobisocial.arcade`), descontinuado em 2023.

> **Status:** login de convidado e retomada de sessão funcionam de ponta a ponta.
> O cliente corrigido completa o handshake WebSocket, cria uma conta de convidado,
> persiste e retoma a sessão após reiniciar. A tela Sobre do perfil renderiza
> nome, nível, contadores zerados, bio, avatar e capa (assets locais de
> placeholder). O feed Início renderiza um post de teste local (autor, título,
> descrição e curtir/comentar/compartilhar; a imagem do post usa o logo padrão) e
> o detalhe do post abre só com texto. Curtidas alternam e persistem entre
> recarregamentos, e comentários podem ser listados e adicionados (em memória).
> Chat/live e mídia do feed ainda **não** estão implementados.

> **Aviso:** este é um projeto não oficial de engenharia reversa / preservação.
> Não é afiliado à Omlet, à Mobisocial nem a seus parceiros. Nenhum APK, código
> proprietário, asset, credencial ou dado de usuário está incluído neste
> repositório. Use apenas com um APK que você possui legalmente, para estudo
> pessoal e pesquisa.

---

## O que funciona

- Handshake challenge/response X25519 do protocolo RPC proprietário **Longdan**
  do cliente sobre WebSocket (`md0` → `nd0` → `he` → `ie`).
- Verificação de disponibilidade do Omlet ID (`ci` → `pz0`).
- Criação de conta de convidado (`sc` → `nz0`/`z`) com cluster `ONE`.
- Retomada de sessão após reiniciar o app (`qb` → `z`) apoiada por um
  armazenamento local de contas (`server/accounts.json`, não versionado).
- O cliente chega à tela Início logado como convidado e mantém a sessão após
  reiniciar.
- Sessão/keepalive (`rp0` → `sp0`).
- Requisições de perfil:
  - `gpa` → `ir0`/`hr0` (Sobre do perfil);
  - `p.c` → `z00`/`se` (detalhes do perfil; o Omlet ID aparece em Configurações
    da Conta);
  - `w.gfc`, `w.gafc`, `w.guwc` → `pz0` (contadores de seguidores/seguindo/posts);
  - `p.gui` → `ra0` (shards);
  - `ca.g` → `uu` (top apoiadores).
- Tickets de blob do avatar/capa do perfil (`b.dt` → `wu`/`y7`) servidos por um
  servidor HTTP local de assets (`server/avatar.png`, `server/cover.png`).
- A tela Sobre do perfil renderiza nome, nível, contadores zerados, bio, avatar e
  capa. Posts/loja/coleções/momentos estão vazios.
- Feed Início: `w.ghp` → `sx`/`td0` retorna um post de teste local com autor
  (`usr`/`dq0`), título/descrição e preview de link. A mídia/imagem do post usa o
  logo padrão da Omlet. Abrir o detalhe do post funciona só com texto (os
  booleanos `yl`/`vd` são preenchidos para evitar o crash antigo do
  `PostViewFragment`).
- Curtidas em posts: o job `w.l` (`jg0`) atualiza o estado de curtida no servidor;
  o feed retorna `yl` e a contagem, então o coração/contagem persistem entre
  recarregamentos.
- Comentários em posts: `w.gcvv` (`kt`) → `lt`/`xd` retorna a lista, e `w.ac`
  (`f0`) adiciona um comentário de texto; a folha de comentários renderiza a lista
  e o feed retorna o `cc` atualizado. Comentários ficam em memória.
- APK corrigido aponta todos os endpoints embutidos para um servidor HTTP/WS local.

Ainda não implementado:

- Conteúdo de perfil (posts, loja, coleções, momentos) e perfis de outros
  usuários.
- Mídia/imagens do feed, múltiplos posts/paginação, threading/respostas e
  persistência de comentários, outras interações, seguir, chat/mensagens, jogos,
  live/streaming.
- Blobs para mídia enviada pelo usuário, notificações push, namespaces de
  billing/NFT/analytics.

---

## Arquitetura

O cliente fala com uma camada RPC proprietária chamada **Longdan**:

- Transporte: **WebSocket**, payloads JSON (respostas servidor → cliente podem ser
  comprimidas com gzip; o cliente também comprime requisições grandes com gzip se
  o servidor anunciar um tamanho máximo).
- Handshake: **X25519** usando uma chave de dispositivo por instalação e chaves
  públicas do servidor embutidas no recurso `res/raw/oml_pk.json` do APK.
- Envelope:

```json
{"q": {"#": <request-id>, "<category>": {"<method>": { ... }}}}
{"r": {"#": <request-id>, "<category>": {"<method>": { ... }}}}
```

Para a conexão IDP/auth (`/device`), o container de requisição é `jl` e o de
resposta é `kl` → `ml`. A conexão de mensagens/somente leitura usa outro par de
containers.

### Endpoints embutidos no APK

`res/raw/oml_pk.json` contém:

- `ClusterEndpoints` — dez clusters regionais (us/sg/cn/de/in/ja/br/au/sk/use).
- `IdpEndpoints` — endpoint do provedor de identidade.
- `ReadOnlyEndpoints` — endpoint de conteúdo somente leitura.
- `ClusterKeys`, `IdpKey`, `ReadOnlyKey` — **chaves públicas do servidor**.
- `DefaultCluster` — `ONE`.

O script de patch substitui todos eles por um endpoint local e uma chave pública
gerada.

### Handshake

O cliente conecta em `<endpoint>/device` (ou `/readonlydevice`) e envia:

```json
{"q":{"#":1,"*":{
  "a":"<omlet.apikey bytes, base64>",
  "c":"<client nonce, 32 bytes, base64>",
  "k":"<client X25519 public key, base64>",
  "s":false,
  "z":true
}}}
```

O servidor calcula:

```text
shared = X25519(server_private, client_public)
server_nonce = random(32)
digest  = SHA256(0x01 || shared || client_nonce)
```

e responde:

```json
{"r":{"#":1,"*":{
  "c":"<server nonce, base64>",
  "r":"<digest, base64>"
}}}
```

O cliente verifica o digest e então envia `he` (`+`) com:

```text
SHA256(0x02 || shared || server_nonce)
```

O servidor responde com `ie` (`+`), que carrega o nome do cluster mais próximo:

```json
{"r":{"#":3,"+":{"l":"ONE"}}}
```

### Login de convidado

1. `ci` verifica se um Omlet ID está disponível. Resposta: `pz0` (`=`), um
   booleano armazenado na chave `v`:

```json
{"r":{"#":7,"=":{"v":true}}}
```

2. `sc` cria/entra na conta de convidado. O servidor responde com `nz0` sob a
   chave `ml` `sc`, dentro da chave `kl` `a`:

```json
{"r":{"#":8,"a":{"sc":{
  "s":"GUEST",
  "a":{
    "a":{"a":"<account-id>","c":"ONE","d":"GUEST",
         "i":[{"p":"<omlet-id>","t":"omlet"}],
         "p":"<omlet-id>","s":<timestamp-ms>},
    "S":["PublicProfile","Arcade"],
    "i":"<app-id, 32 bytes, base64>",
    "e":false,
    "p":false
  }
}}}}
```

Depois disso o cliente armazena a conta e reconecta o canal de mensagens ao
endpoint do cluster.

---

## Estrutura do repositório

```text
.
├── README.md
├── LICENSE
├── .gitignore
├── server/
│   ├── server.py            # handshake, sessões e servidor de perfil
│   ├── avatar.png          # avatar padrão servido ao cliente
│   ├── cover.png           # capa padrão do perfil
│   ├── stub.py             # logger WebSocket bruto (depuração de protocolo)
│   ├── generate_keys.py    # cria server/keys.json
│   └── requirements.txt
└── scripts/
    └── patch-apk.sh         # decodifica/corrige/reconstrói/assina o APK do cliente
```

Em tempo de execução o servidor cria `server/accounts.json` para persistir contas
de convidado entre reinícios. Esse arquivo é ignorado pelo Git.

O APK original, a árvore decompilada, os APKs reconstruídos, os logs, a chave
privada e o keystore de assinatura **não** são versionados intencionalmente.

---

## Requisitos

Testado em Arch Linux + Waydroid (LineageOS 20, x86_64). Você precisa de:

- Linux com Waydroid (ou um dispositivo Android físico com ADB).
- Python 3.11+.
- `apktool`, `zipalign`, `apksigner`, `keytool` (Java).
  - No Arch, `apktool` está disponível no AUR; as build-tools fornecem
    `zipalign`/`apksigner` (ex.: `/opt/android-sdk/build-tools/33.0.2`).
- O APK original `omlet-arcade-1-111-9.apk` (não distribuído aqui).
- `adb` do pacote `android-tools`.

O APK original embute as credenciais do app (`omlet.apikey` e `omlet.secret`) no
manifest. O servidor não precisa conhecê-las; o cliente envia a API key durante o
handshake e o servidor a aceita. Elas não estão incluídas neste repositório.

---

## Início rápido

### 1. Ambiente Python

```bash
python3 -m venv server/venv
server/venv/bin/pip install -r server/requirements.txt
```

### 2. Gerar o par de chaves do servidor local

```bash
python3 server/generate_keys.py
```

Isso cria `server/keys.json` (chave privada + chave pública). **Nunca versione
esse arquivo.** A chave pública é a que será embutida no APK.

### 3. Corrigir o APK

```bash
scripts/patch-apk.sh /path/to/omlet-arcade-1-111-9.apk
```

Um segundo argumento opcional sobrescreve o host/porta (padrão
`192.168.240.1:8080`, o gateway do host no Waydroid):

```bash
scripts/patch-apk.sh /path/to/omlet.apk 192.168.240.1:8080
```

O script:

1. decodifica recursos/manifest com `apktool` (sem mudanças em smali);
2. reescreve `res/raw/oml_pk.json` para apontar todos os endpoints para seu host e
   usar a chave pública de `server/keys.json`;
3. habilita tráfego cleartext para o host local;
4. habilita o fluxo de conta de convidado (`omlet.guest=true`);
5. reconstrói, alinha e assina com `tools/debug.keystore` (gerado sob demanda).

Saída: `patched/omlet-patched-signed.apk`.

> O build consome muita memória. Pare o Waydroid e feche navegadores pesados antes
> de rodar. O script usa `-j1` e `-JXmx6g` para reduzir a pressão de memória.

### 4. Waydroid + ADB

```bash
sudo systemctl enable --now waydroid-container
waydroid session start &
waydroid show-full-ui       # desbloqueia / mostra a UI do Android
waydroid adb connect        # ou: adb connect 192.168.240.112:5555
adb devices
```

Se o ADB mostrar `unauthorized`, adicione sua chave do host dentro do container:

```bash
cat ~/.android/adbkey.pub | sudo waydroid shell -- \
  sh -c 'mkdir -p /data/misc/adb; cat > /data/misc/adb/adb_keys; \
         chmod 640 /data/misc/adb/adb_keys; chown system:shell /data/misc/adb/adb_keys'
sudo waydroid shell -- setprop ctl.restart adbd
adb kill-server && adb connect 192.168.240.112:5555
```

### 5. Instalar o APK corrigido

Diferente da assinatura original, o APK corrigido precisa substituir o app
instalado:

```bash
sudo waydroid shell -- pm uninstall mobisocial.arcade
adb install -r -d patched/omlet-patched-signed.apk
```

Se `waydroid app install` sair instantaneamente sem instalar (problema conhecido
do helper), use `adb install` ou envie o APK para `/data/local/tmp` e rode
`pm install` manualmente.

### 6. Iniciar o servidor

```bash
cd server
nohup ./venv/bin/python server.py >> ../logs/server.log 2>&1 &
```

O servidor escuta em `0.0.0.0:8080`. O cliente alcança o host em
`192.168.240.1:8080` de dentro do Waydroid.

### 7. Abrir o app

```bash
adb shell am start -W -n mobisocial.arcade/.DEFAULT
```

Crie uma conta de convidado:

1. toque em **Create Account**;
2. informe um ID (6–20 caracteres, letras minúsculas, dígitos, ponto, underscore);
3. aguarde o check verde (`ci` deu certo);
4. toque em **CONTINUE** (`sc` cria a conta);
5. pule o onboarding opcional de gênero/aniversário.

Você deve chegar à tela Início.

---

## Notas de protocolo

### Categorias de requisição/resposta

Na conexão IDP:

| Chave | Significado |
| --- | --- |
| `*` | requisição de handshake `md0` / resposta de handshake `nd0` |
| `+` | conclusão do hello `he` / resposta do hello `ie` |
| `-` | requisição keepalive `rp0` / resposta keepalive `sp0` |
| `a` | container de auth (requisição `ll` / resposta `ml`) |
| `=` | resposta genérica `pz0` (usada por `ci`) |

A verificação `ci` e o login `sc` ficam dentro do container `a`:

```json
{"q":{"a":{"ci":{...}}}}
{"r":{"#":7,"=":{"v":true}}}
{"q":{"a":{"sc":{...}}}}
{"r":{"#":8,"a":{"sc":{...nz0...}}}}
```

### Keepalive

O cliente envia `rp0` periodicamente:

```json
{"q":{"#":2,"-":{"l":0,"n":28000}}}
```

Responda com o timestamp do servidor:

```json
{"r":{"#":2,"-":{"t":<epoch-ms>}}}
```

### Depuração

`server/stub.py` é um logger WebSocket bruto. Ele não responde ao handshake;
apenas imprime paths e mensagens (texto ou gzip/binário) para você capturar
exatamente o que o cliente envia.

```bash
server/venv/bin/python server/stub.py
```

---

## Limitações conhecidas / roadmap

- **Mídia/conteúdo de perfil**: o avatar e a capa são assets locais de
  placeholder; posts/loja/coleções/momentos do perfil estão vazios.
- **Feed Início**: um post de teste local é servido e o detalhe abre só com
  texto; curtidas persistem e comentários podem ser listados/adicionados em
  memória, mas mídia do feed, múltiplos posts, paginação, persistência/threading
  de comentários e outras interações não estão implementados.
- **Chat/mensagens** não está implementado.
- **Live/streaming** não está implementado; o app original dependia de
  RTMP/SRT/WebRTC externos e plataformas de terceiros.
- **Blobs / push / billing / NFT / analytics** não estão implementados.
- Chamadas de analytics/billing vão logar erros na UI do cliente; são inofensivas
  para os marcos de login/sessão/perfil.

---

## Solução de problemas

### Crash gráfico do Waydroid/Android ao iniciar

Em algumas configurações AMD/Mesa + Hyprland, iniciar o Waydroid pode derrubar o
compositor junto com o `surfaceflinger` (um abort do Mesa/GBM). Atualizar
Mesa/Hyprland/kernel e firmware resolveu no nosso teste. Se ainda acontecer,
tente renderização por software:

```bash
sudo waydroid prop set persist.waydroid.software_rendering true
```

e evite manter a UI do Waydroid aberta durante builds pesados.

### `waydroid app install` retorna sucesso mas não instala nada

Isso aconteceu no Waydroid 1.6.3 com um APK grande. Use ADB:

```bash
adb install -r -d patched/omlet-patched-signed.apk
```

ou copie o APK para `/data/local/tmp` do container e rode:

```bash
sudo waydroid shell -- pm install -r /data/local/tmp/omlet.apk
```

### ADB `unauthorized`

Adicione `~/.android/adbkey.pub` a `/data/misc/adb/adb_keys` dentro do container
(veja o passo 4) e reinicie o `adbd`.

### O cliente não alcança o servidor

- Confirme que o servidor está escutando: `ss -ltnp | grep 8080`.
- Confirme que o APK foi corrigido com o mesmo host do servidor (padrão
  `192.168.240.1:8080`).
- Confirme que HTTP cleartext é permitido no
  `network_security_config.xml` corrigido.
- A chave pública no APK deve bater com `server/keys.json`; rode o script de
  patch de novo após regerar as chaves.

---

## Legal

Omlet Arcade, seu cliente, protocolo, marcas e assets pertencem aos respectivos
donos. Este repositório contém apenas código e documentação originais produzidos
para pesquisa de interoperabilidade. Nenhum APK, código proprietário
decompilado, asset, credencial ou dado de usuário é distribuído aqui. Não use
este projeto para acessar contas ou dados de outras pessoas, e não redistribua
APKs modificados.

## Licença

O código e a documentação deste repositório são liberados sob a Licença MIT (veja
`LICENSE`). Esta licença **não** concede quaisquer direitos sobre o Omlet Arcade
ou propriedade intelectual de terceiros.
