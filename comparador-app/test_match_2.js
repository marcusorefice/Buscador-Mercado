const allProducts = [
  { id: 1, Mercado: 'Atacadão', Produto: 'AÇÚCAR REFINADO', Marca: 'UNIÃO', Preco_Varejo: '2.50' },
  { id: 2, Mercado: 'Tauste Supermercado', Produto: 'ACUCAR REFINADO UNIAO', Marca: 'UNIAO', Preco_Varejo: '2.60' },
  { id: 3, Mercado: 'Covabra', Produto: 'Açúcar Refinado Especial União', Marca: null, Preco_Varejo: '2.70' },
  { id: 4, Mercado: 'Carrefour', Produto: 'Açúcar Refinado União', Marca: 'União', Preco_Varejo: '2.80' }
];

const product = allProducts[0];

const normalize = (str) => {
  if (!str) return '';
  return str.trim().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
};

const getComparisons = () => {
    if (!product || !allProducts) return [];
    
    const prodName = normalize(product.Produto);
    const prodBrand = normalize(product.Marca);
    
    const ignoreWords = ['de', 'com', 'em', 'sem', 'ao', 'para', 'e'];
    const keywords = prodName.split(' ').filter(w => w.length > 2 && !ignoreWords.includes(w));
    const coreKeywords = keywords.slice(0, 3); 
    
    const matches = allProducts
      .filter((p) => {
        if (p.id === product.id || p.Mercado === product.Mercado) return false;
        
        const pName = normalize(p.Produto);
        const pBrand = normalize(p.Marca);
        
        // 1. Marca: Se um tem marca e o outro também, elas PRECISAM ser iguais.
        // Se um deles não tem marca explícita, a gente relaxa e confia só no nome.
        const isGeneric = (b) => !b || b === 'n/a' || b === 'propria';
        const brandA = isGeneric(prodBrand) ? null : prodBrand;
        const brandB = isGeneric(pBrand) ? null : pBrand;
        
        if (brandA && brandB && brandA !== brandB) return false;

        // 2. Nome exato
        if (pName === prodName) return true;

        // 3. Fuzzy Match
        if (coreKeywords.length > 0) {
           const matchCount = coreKeywords.filter(kw => pName.includes(kw)).length;
           // Se bater todas as palavras-chave e pelo menos uma marca coincidir ou ambas nulas
           if (matchCount === coreKeywords.length) return true;
        }

        return false;
      });

      return matches;
}

console.log(getComparisons());