/*Change numerical base of input number x to base.
  return string representation after the conversion.
  base numbers are less than 10.
  >>> changeBase(8, 3)
  '22'
  >>> changeBase(8, 2)
  '1000'
  >>> changeBase(7, 2)
  '111'
  */
const changeBase = (x, base) => {
  var ret = "";
  while (x > 0) {
    ret = (x % base).toString() + ret;
    x = Math.floor(x / base);
  }
  return ret;
}

