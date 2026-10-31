// Preço no formato brasileiro: 1234.5 -> "1.234,50"
export const formatPrice = (value: number) => {
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
