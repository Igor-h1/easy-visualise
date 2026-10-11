# 🎬 Easy Visualise

Aplicativo com interface gráfica para facilitar o download e a conversão de arquivos de áudio e vídeo, utilizando ferramentas externas instaladas e configuradas pelo próprio usuário.

O Easy Visualise atua como uma interface de interação com ferramentas de terceiros, buscando simplificar sua utilização por meio de recursos gráficos, gerenciamento de tarefas e opções de processamento de mídia.

## 📋 Funcionalidades

### 🎬 Download de vídeos e áudios

Integração com o `yt-dlp`, ferramenta externa que deve ser obtida e configurada separadamente pelo usuário.

- Suporte a vídeos individuais e playlists, conforme a compatibilidade da ferramenta e da plataforma de origem.
- Seleção de formatos de saída, como MP3 e MP4.
- Escolha de qualidade, quando disponível.
- Fila de downloads com possibilidade de edição.
- Consulta de formatos e qualidades disponíveis, conforme os recursos da ferramenta externa.

### 🔄 Conversor de mídia

Integração com o FFmpeg, ferramenta externa que deve ser obtida e configurada separadamente pelo usuário.

- **Áudio para áudio:** MP3, WAV, FLAC, AAC, OGG e OPUS.
- **Vídeo para vídeo:** MP4, MKV, AVI, MOV, WEBM, MPEG-2 e FLV.
- **Vídeo para áudio:** extração de áudio de arquivos de vídeo.
- **Vídeo para GIF:** criação de animações.
- **Corte de mídia:** seleção de trechos de áudio e vídeo.

A disponibilidade de cada operação depende da implementação do aplicativo, da instalação correta das ferramentas externas e dos codecs disponíveis.

## 🛠️ Dependências externas

O Easy Visualise não realiza a instalação automática nem o download automático das ferramentas externas necessárias ao seu funcionamento.

O usuário é responsável por localizar, obter, instalar e configurar as dependências exigidas, bem como por verificar sua compatibilidade com o sistema operacional e com a versão do aplicativo utilizada.

As principais ferramentas externas são:

- **yt-dlp:** utilizada para operações de download de mídia compatíveis com a ferramenta.
  - Projeto oficial: https://github.com/yt-dlp/yt-dlp
- **FFmpeg:** utilizado para conversão, processamento e extração de mídia.
  - Site oficial: https://ffmpeg.org/

O Easy Visualise não inclui necessariamente os executáveis dessas ferramentas em seu código-fonte ou pacote de distribuição. Salvo indicação expressa em contrário, eles devem ser obtidos separadamente pelo usuário, a partir de fontes confiáveis.

A instalação, a atualização e a configuração dessas dependências são de responsabilidade do usuário. O funcionamento das funcionalidades correspondentes depende de que as ferramentas estejam corretamente instaladas e acessíveis ao aplicativo.

## ⚖️ Aviso legal

O Easy Visualise é um projeto independente e não possui, por essa razão, afiliação oficial, patrocínio ou endosso dos projetos yt-dlp ou FFmpeg.

O aplicativo fornece uma interface para interagir com ferramentas externas. A integração técnica não concede direitos sobre conteúdos de terceiros nem autoriza operações que sejam proibidas pela legislação ou pelas condições aplicáveis aos serviços utilizados.

O usuário é responsável por verificar se possui autorização ou outra base jurídica válida para baixar, reproduzir, converter, armazenar ou compartilhar os conteúdos que utilizar.

A utilização do aplicativo deve respeitar a legislação aplicável, incluindo a Lei nº 9.610/1998 (Lei de Direitos Autorais), os direitos de terceiros e as condições de uso das plataformas de origem.

A possibilidade técnica de realizar um download ou uma conversão não significa que a operação esteja necessariamente autorizada.

O aplicativo não deve ser utilizado para violar direitos autorais, obter acesso não autorizado a conteúdo ou contornar medidas tecnológicas de proteção sem autorização ou fundamento jurídico válido.

## 🔒 Responsabilidades e limitações

O usuário é responsável pela obtenção e configuração das ferramentas externas, pela origem dos arquivos processados e pela finalidade de uso dos recursos disponíveis no aplicativo.

O desenvolvedor não garante a compatibilidade permanente com plataformas de terceiros, cujo funcionamento pode mudar independentemente do projeto.

Na máxima extensão permitida pela legislação aplicável, o desenvolvedor não se responsabiliza por usos indevidos realizados por usuários nem por falhas ou indisponibilidades de ferramentas e serviços externos fora de seu controle. Esta disposição não exclui responsabilidades que não possam ser afastadas por lei.

## 📜 Licenciamento

O Easy Visualise possui licença própria, que deve ser especificada no arquivo `LICENSE` do repositório.

As ferramentas externas utilizadas pelo aplicativo mantêm suas próprias licenças. Como o projeto não as distribui automaticamente, o usuário deve consultar as condições oficiais de cada ferramenta ao obtê-la, instalá-la ou redistribuí-la.

A licença do Easy Visualise não substitui nem modifica as licenças dos projetos de terceiros.

## ⚠️ Nota

Este documento apresenta informações gerais sobre a finalidade e as condições de utilização do projeto. Não constitui aconselhamento jurídico nem garante, isoladamente, conformidade com todas as obrigações legais aplicáveis.