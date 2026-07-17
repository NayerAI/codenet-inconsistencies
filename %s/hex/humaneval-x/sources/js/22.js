/* Filter given list of any python values only for integers
  >>> filterIntegers(['a', 3.14, 5])
  [5]
  >>> filterIntegers([1, 2, 3, 'abc', {}, []])
  [1, 2, 3]
  */
const filterIntegers = (values) => {
  return values.filter(x => Number.isInteger(x));
}

