const allProducts = [
  {
    id: 1,
    Mercado: 'Atacadão',
    Produto: 'CERVEJA PILSEN',
    Marca: 'SKOL',
    Preco_Varejo: '2.50'
  },
  {
    id: 2,
    Mercado: 'Tauste Supermercado',
    Produto: 'CERVEJA PILSEN',
    Marca: 'SKOL',
    Preco_Varejo: '2.60'
  },
  {
    id: 3,
    Mercado: 'Covabra',
    Produto: 'CERVEJA PILSEN LATA 350ML',
    Marca: 'SKOL',
    Preco_Varejo: '2.70'
  }
];

const product = allProducts[0];

const capitalize = (str) => {
  if (!str) return '';
  return str.toLowerCase().replace(/(?:^|\s)\S/g, (a) => a.toUpperCase());
};

const getComparisons = () => {
    if (!product || !allProducts) return [];
    
    const prodName = capitalize(product.Produto).toLowerCase();
    const prodBrand = capitalize(product.Marca).toLowerCase();
    
    // Extrai palavras-chave principais do produto (ex: 'cerveja pilsen lata' -> ['cerveja', 'pilsen'])
    const ignoreWords = ['de', 'com', 'em', 'sem', 'ao', 'para', 'e'];
    const keywords = prodName.split(' ').filter(w => w.length > 2 && !ignoreWords.includes(w));
    const coreKeywords = keywords.slice(0, 3); // Usa as 3 primeiras palavras mais fortes
    
    const matches = allProducts
      .filter((p) => {
        if (p.id === product.id || p.Mercado === product.Mercado) return false;
        
        const pName = capitalize(p.Produto).toLowerCase();
        const pBrand = capitalize(p.Marca).toLowerCase();
        
        // 1. Marca tem que bater
        const hasBrand = prodBrand && prodBrand !== 'n/a' && prodBrand !== 'própria';
        if (hasBrand && pBrand !== prodBrand) return false;
        if (!hasBrand && pBrand !== prodBrand) return false; // Se for sem marca, só compara com sem marca

        // 2. Nome exato
        if (pName === prodName) return true;

        // 3. Nome parecido (Fuzzy Match pelas palavras-chave)
        if (hasBrand && coreKeywords.length > 0) {
           const matchCount = coreKeywords.filter(kw => pName.includes(kw)).length;
           // Se o produto rival contiver todas as 2 ou 3 palavras-chave principais E a mesma marca
           if (matchCount === coreKeywords.length) return true;
        }

        return false;
      })

      return matches;
}

console.log(getComparisons());