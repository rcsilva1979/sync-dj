import os
import string

class VDJManager:
    def __init__(self):
        self.settings_path = self.localizar_settings_xml()
        self.vdj_dirs = self.mapear_diretorios_vdj()

    def localizar_settings_xml(self):
        """Tenta localizar o arquivo settings.xml no caminho padrão do Windows (AppData/Local)."""
        local_app_data = os.environ.get('LOCALAPPDATA')
        if local_app_data:
            path = os.path.join(local_app_data, "VirtualDJ", "settings.xml")
            if os.path.exists(path):
                return path
        return None

    def mapear_diretorios_vdj(self):
        """
        Localiza as pastas de dados do VirtualDJ no sistema e discos extras.
        Retorna uma lista de pastas que contêm o banco de dados 'database.xml'.
        """
        candidatos = []
        
        # 1. Locais no disco do sistema (C:)
        # AppData Local (Sugerido pelo usuário)
        local_app = os.environ.get('LOCALAPPDATA')
        if local_app: candidatos.append(os.path.join(local_app, "VirtualDJ"))
        
        # Documents (Padrão clássico do Windows)
        user_profile = os.environ.get('USERPROFILE')
        if user_profile: candidatos.append(os.path.join(user_profile, "Documents", "VirtualDJ"))

        # 2. Varre a raiz de todos os discos (D:, E:, etc) para pastas na raiz
        for letra in string.ascii_uppercase:
            root = f"{letra}:\\"
            if os.path.exists(root):
                path_vdj = os.path.join(root, "VirtualDJ")
                if path_vdj not in candidatos:
                    candidatos.append(path_vdj)

        # Filtra apenas pastas que realmente existem
        return [p for p in candidatos if os.path.exists(p)]

    def localizar_diretorios_folders(self):
        """
        Varre as pastas mapeadas em busca das subpastas 'MyLists' e 'My List'.
        Retorna uma lista de caminhos absolutos existentes.
        """
        caminhos_alvo = []
        for base in self.vdj_dirs:
            for sub in ["MyLists", "My List"]:
                path = os.path.join(base, sub)
                if os.path.exists(path):
                    caminhos_alvo.append(path)
        return caminhos_alvo

    def verificar_instalacao(self):
        """Retorna True se o arquivo de configuração ou pastas de dados foram encontrados."""
        return self.settings_path is not None or len(self.vdj_dirs) > 0