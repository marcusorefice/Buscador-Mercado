const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

// Na web, o zustand (build ESM) usa import.meta, que o navegador não aceita em script comum.
// Sem "exports" do package.json o Metro cai no build CommonJS e a tela volta a carregar.
config.resolver.unstable_enablePackageExports = false;

module.exports = config;
