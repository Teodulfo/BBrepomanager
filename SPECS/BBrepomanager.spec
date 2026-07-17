Summary: 	Ferramenta de gerência dos repositórios dos TMFs no servidor
Name:		BBrepomanager
Version:	1.0
Release:	1.2
License:	SUSE-NonFree
Group:		System/Management
Url:        http://git.autoban.desenv.bb.com.br/aplicativos/bbrepoman

#
# ATENÇÃO:	Os fontes do bbrepoman deve ser sempre atualizados no git em
#			http://git.autoban.desenv.bb.com.br/aplicativos/bbrepoman
#
Source1:	bbrepoman.py
Source2:	preset.systemd
Source3:	service.systemd
Source4:	timer.systemd

BuildRoot:	%{_tmppath}/%{name}-%{version}-build
BuildArch:	noarch
Requires:   coreutils
Requires:	python3-tqdm
Requires:	python3-dbus-python

# Para formatar resultados com `column`
Recommends: util-linux >= 2.30

# Sem isso o script apresenta uma mensagem de erro quando roda.
%if 0%{?suse_version} >= 1500
Requires:	user(wwwrun)
Requires:	group(www)
%else
Requires:	apache2
%endif

# Precisa do serviço SLPD para ativar/desativar a detecção automática de repositório
Requires:	openslp-server

# O BBvisualizador 1.5.0 toma posse da porta 80 impedindo o serviço de instalação
Conflicts: BBvisualizadorAG <= 1.5.0

Requires:	BBrepomanager-conf >= 0.2.0

%{systemd_requires}

%description
Ferramenta para realizar o gerenciamento do processo de sincronização de 
repositórios no servidor de agência.
Para agilizar e flexibilizar a instalação de TMFs, os repositórios de instalação
são disponibilizados na rede através do protocolo SLP. Esta ferramenta foi
criada para permitir o gerenciamento destes de forma mais padronizada e 
automatizada. Versão reescrita em Python.

Referência: https://redmine.intranet.bb.com.br/issues/6130

%prep

%build

%install
#repoman
mkdir -p %{buildroot}%{_bindir}
install -m 755 %{S:1}  %{buildroot}%{_bindir}/bbrepoman

# Systemd
mkdir -p %{buildroot}%{_unitdir}
mkdir -p %{buildroot}%{_presetdir}
mkdir -p %{buildroot}%{_sbindir}
mkdir -p %{buildroot}%{_sysconfdir}/BBrepomanager
install -m 644 %{S:2} %{buildroot}%{_presetdir}/90-bbrepoman.preset
install -m 644 %{S:3} %{buildroot}%{_unitdir}/bbrepoman.service
install -m 644 %{S:4} %{buildroot}%{_unitdir}/bbrepoman.timer
ln -s %{_sbindir}/service %{buildroot}%{_sbindir}/rcbbrepoman

#BBrepomanager.cache
mkdir -p %{buildroot}/var/cache/BBrepomanager
 
%post
%service_add_post bbrepoman.service
%service_add_post bbrepoman.timer

%posttrans
/usr/bin/systemctl daemon-reload
if [ -e %{_unitdir}/bbrepoman.timer ]; then
	echo "Ativando timer %{name}"
	/usr/bin/systemctl enable bbrepoman.timer
	/usr/bin/systemctl restart bbrepoman.timer
fi

if [ -e %{_unitdir}/bbrepoman.service ]; then
	echo "Ativando serviço %{name}"
	/usr/bin/systemctl enable bbrepoman.service
fi

# se for upgrade, dá restart no serviço
if [ $1 == 2 ]; then
	/usr/bin/systemctl restart bbrepoman.service
fi

%pre
%service_add_pre bbrepoman.service
%service_add_pre bbrepoman.timer

%postun
%service_del_postun bbrepoman.service
%service_del_postun bbrepoman.timer

%preun
%service_del_preun bbrepoman.service
%service_del_preun bbrepoman.timer

%files
%defattr(-,root,root)

%dir /var/cache/BBrepomanager
%dir %{_sysconfdir}/BBrepomanager

%{_bindir}/bbrepoman

%dir %{_presetdir}
%{_presetdir}/*
%{_unitdir}/*
%{_sbindir}/rcbbrepoman

%changelog
* Fri Jun 19 2026 c1313204@interno.bb.com.br
- Ajustado os caminhos usados pelo projeto no disco, utilizando o padrão do SLE15sp7.
- Ajustado a criação dos CHECKSUMS, apenas com arquivos [.rpm]
* Thu Feb  8 2024 erico.mendonca@suse.com
- Alterando porta baseado no campo http_port do XML.
* Fri Jan  5 2024 erico.mendonca@suse.com
- Versão 1.0: reescrevendo em Python (ver https://redmine.intranet.bb.com.br/issues/6130 para detalhes da implementação)
- Consolidando changelog
- Ajustes no SPEC
* Thu Dec 21 2023 c1103788@interno.bb.com.br
- Corrigindo tratamento do '*' no arquivo sha1sum
* Wed Jun  7 2023 c1103788@interno.bb.com.br
- Ticket #5486: Corrigindo problemas na geração dos arquivos de controle SLPD.
* Wed Mar 15 2023 erico.mendonca@suse.com
- Corrigindo licença.
* Tue Jul 12 2022 c1103788@interno.bb.com.br
- Mudando para serviço e timer systemd. A validação ocorre uma vez no boot da máquina e, depois, uma vez a cada 24 horas.
- Serviço SLP não é mais habilitado, agora ele sobe ou desce de acordo com o resultado do teste de repositório.
* Tue Dec 28 2021 erico.mendonca@suse.com
- Melhorando a usabilidade do parâmetro "verificar".
* Mon Jul 26 2021 c1313204@interno.bb.com.br
- Desmembrada a informações dos repositórios do código fonte, será criado o BBrepomanager-conf, com as informações das distribuições/repositórios.
* Wed Jun 24 2020 gruas@bb.com.br - 0.13-1
- Comando status consulta todos os repositorios disponíveis
- Comando extrair opera apenas em repositórios inconsistentes
- Suporte à nova forma de distribuição dos repos SLE15
- Correção na validação do nome das flags
- Correção no ajuste do proprietário dos repositórios
* Thu Jun 18 2020 gruas@bb.com.br - 0.12-1
- Corrige propriedade dos arquivos extraídos
- Suprime mensagem de erro do column antigo
* Mon Jun 15 2020 gruas@bb.com.br - 0.11-1
- Adiciona arquivo de configuração para apache no SLE 11
- Adiciona charset ao script flags
* Wed Jun 10 2020 gruas@bb.com.br - 0.10-1
- Correções no comando cache
* Fri Jun  5 2020 gruas@bb.com.br - 0.9-1
- Inclui guarda do mod_rewrite
- Suprime erros dos scriptlets
* Wed Jun  3 2020 gruas@bb.com.br - 0.8-1
- Reinicia apache após a instalação
- Corrige status
* Tue Jun  2 2020 gruas@bb.com.br - 0.7-1
- Adiciona CGI para flags
* Thu May 28 2020 gruas@bb.com.br - 0.6-1
- Correção invalidar_status
* Wed May 27 2020 gruas@bb.com.br - 0.5-1
- Inclui script cron para execução diária
* Mon May 25 2020 gruas@bb.com.br - 0.4-1
- Suporte aos repositórios no SLES11
* Fri May 22 2020 gruas@bb.com.br - 0.3-2
- Diretório de status incluido na lista de arquivos
* Thu May 21 2020 gruas@bb.com.br - 0.3-1
- Corrige caso em que o diretório de status não existe
* Thu May 21 2020 gruas@bb.com.br - 0.2-1
- Armazena resultados da verificação (status)
- Permite carregar arquivo de configuração
- Permite selecionar o cache
- Suporte aos repositorios SLE15SP1
* Mon Apr 27 2020 gruas@bb.com.br - 0.1-1
- Versão inicial
