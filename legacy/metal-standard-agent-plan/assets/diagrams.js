(function () {
  if (typeof mermaid === 'undefined') return;

  mermaid.initialize({
    startOnLoad: true,
    securityLevel: 'loose',
    theme: 'base',
    themeVariables: {
      fontFamily: '"Work Sans", "Microsoft YaHei", "PingFang SC", sans-serif',
      fontSize: '13px',
      primaryColor: '#edeae3',
      primaryTextColor: '#1b1e21',
      primaryBorderColor: '#a34e22',
      secondaryColor: '#e4e0d7',
      secondaryTextColor: '#1b1e21',
      secondaryBorderColor: '#d5d0c5',
      tertiaryColor: '#f7f5f0',
      tertiaryTextColor: '#1b1e21',
      tertiaryBorderColor: '#d5d0c5',
      lineColor: '#2b5560',
      textColor: '#1b1e21',
      clusterBkg: '#f2efe8',
      clusterBorder: '#d5d0c5',
      edgeLabelBackground: '#f7f5f0',
      actorBkg: '#edeae3',
      actorBorder: '#a34e22',
      actorTextColor: '#1b1e21',
      signalColor: '#2b5560',
      signalTextColor: '#1b1e21',
      labelBoxBkgColor: '#edeae3',
      labelBoxBorderColor: '#d5d0c5',
      labelTextColor: '#1b1e21',
      loopTextColor: '#1b1e21',
      noteBkgColor: '#e4e0d7',
      noteBorderColor: '#d5d0c5',
      noteTextColor: '#1b1e21'
    }
  });
})();
