/* Return a string containing space-delimited numbers starting from 0 upto n inclusive.
  >>> stringSequence(0)
  '0'
  >>> stringSequence(5)
  '0 1 2 3 4 5'
  */
const stringSequence = (n) => {
  return [...Array(n).keys(), n].join(' ')
}

