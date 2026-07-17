/*Return only positive numbers in the list.
  >>> getPositive([-1, 2, -4, 5, 6])
  [2, 5, 6]
  >>> getPositive([5, 3, -5, 2, -3, 3, 9, 0, 123, 1, -10])
  [5, 3, 2, 3, 9, 123, 1]
  */
const getPositive = (l) => {
  return l.filter(e => e > 0);
}

