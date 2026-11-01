import { formatPrice } from '../formatar';

describe('formatPrice', () => {
  it('usa vírgula decimal, ponto de milhar e sempre 2 casas', () => {
    expect(formatPrice(0)).toBe('0,00');
    expect(formatPrice(5)).toBe('5,00');
    expect(formatPrice(149.9)).toBe('149,90');
    expect(formatPrice(1234.5)).toBe('1.234,50');
    expect(formatPrice(1234567.891)).toBe('1.234.567,89');
  });
});
