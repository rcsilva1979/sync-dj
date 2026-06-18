# Sync DJ Tools
Uma suíte poderosa de ferramentas para DJs que utilizam o ecossistema **Engine DJ (Denon DJ / Numark)**. Este aplicativo automatiza tarefas complexas de gerenciamento de biblioteca, sincronização de arquivos e metadados.

## 🚀 Funcionalidades Principais

### 1. Mirror Sync (Pasta → Engine DJ)
A ferramenta principal para manter sua biblioteca sincronizada com a organização de pastas do seu computador.
*   **Espelhamento de Pastas:** Transforma sua estrutura de pastas do Windows/macOS em Playlists e sub-playlists dentro do Engine DJ.
*   **Sincronização Inteligente:** Adiciona novas músicas e gerencia referências existentes.
*   **Limpeza de Órfãs:** Opção para remover automaticamente da coleção as músicas que foram deletadas ou movidas do seu disco.
*   **Backup Automático:** Realiza cópia de segurança do banco de dados `m.db` antes de qualquer alteração crítica.
*   **Multi-Database:** Suporte para gerenciar múltiplos HDs/SSD Externos simultaneamente.

### 2. Mixed In Key Hotcue Sync
Sincronize seus pontos de Hotcue preparados em softwares externos diretamente para o Engine DJ.
*   **Importação de Tags:** Lê Hotcues gravados nos metadados de arquivos MP3 (gerados por Mixed In Key ou Serato).
*   **Modos de Mesclagem:** Escolha entre apenas preencher slots vazios ou sobrescrever Hotcues existentes no Engine.
*   **Relatórios Detalhados:** Visualização prévia de quais cues serão importados antes de gravar no banco de dados.

### 3. Sync VDJ (Engine DJ ⟷ Virtual DJ)
Integração bidirecional entre os dois softwares.
*   **Engine para VDJ:** Exporta suas Playlists do Engine DJ para o formato `.vdjfolder`, permitindo que o Virtual DJ reconheça sua estrutura de pastas.
*   **VDJ para Engine:** Importa playlists do Virtual DJ para dentro da coleção do Engine DJ.
*   **Conversor CSV:** Utilitário para converter listas de exportação CSV do Engine DJ em arquivos XML compatíveis com o Virtual DJ.

### 4. Relocate Lost Tracks (Fix Paths)
Recupere músicas que aparecem como "vermelhas" ou não encontradas.
*   **Scan Recursivo:** Busca arquivos movidos em pastas específicas.
*   **Atualização de Banco:** Corrige o caminho (path) no banco de dados sem perder seus Hotcues, Loops e Grid.
*   **Busca Inteligente (Fuzzy):** Localiza arquivos mesmo que tenham sido levemente renomeados.

### 5. Shazam Song Discovery
Mantenha seus metadados atualizados.
*   **Identificação de Músicas:** Utiliza tecnologia de reconhecimento para identificar faixas.
*   **Atualização de Tags:** Corrige Artista, Título e Álbum.
*   **Download de Capas:** Busca e insere a arte do álbum (Artwork) diretamente no arquivo.

---

## 🛠️ Detalhes Técnicos

*   **Linguagem:** Python 3.x
*   **Interface Gráfica:** `CustomTkinter` para um visual moderno e sombrio (Pro Audio Style).
*   **Banco de Dados:** Manipulação direta de SQLite3 (`m.db`).
*   **Compatibilidade:** Multiplataforma (Windows e macOS).
*   **Logs e Debug:** Sistema de logging detalhado para auditoria de todas as alterações feitas nos bancos de dados.

## 📦 Requisitos

1.  O **Engine DJ** deve estar fechado durante as operações de escrita no banco de dados.
2.  Arquivos de música devem estar, preferencialmente, no mesmo drive que o banco de dados `Engine Library` para garantir a portabilidade.

## 📖 Como Usar

1.  Execute o `main.py` para abrir o **Launcher Hub**.
2.  Selecione a ferramenta desejada no menu principal.
3.  Configure os caminhos da pasta de músicas e do banco de dados (o app tenta detectar automaticamente nos discos conectados).
4.  Clique no botão de ação e acompanhe o progresso pela barra de status.
5.  Ao final, revise o relatório de alterações gerado na pasta `Reports`.

---

*Desenvolvido para facilitar o fluxo de trabalho de DJs que buscam organização e agilidade.*
