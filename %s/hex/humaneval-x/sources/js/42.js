/*Return list with elements incremented by 1.
  >>> incrList([1, 2, 3])
  [2, 3, 4]
  >>> incrList([5, 3, 5, 2, 3, 3, 9, 0, 123])
  [6, 4, 6, 3, 4, 4, 10, 1, 124]
  */
const incrList = (l) => {
  return l.map(e => e + 1);
}

