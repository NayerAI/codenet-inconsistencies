 
// Implement the Function F that takes n as a parameter,
// and returns a list of size n, such that the value of the element at index i is the factorial of i if i is even
// or the sum of numbers from 1 to i otherwise.
// i starts from 1.
// the factorial of i is the multiplication of the numbers from 1 to i (1 * 2 * ... * i).
// Example:
// F(5) == [1, 2, 6, 24, 15]
func F(n int) []int {
    ret := make([]int, 0, 5)
    for i:=1;i<n+1;i++{
        if i%2 == 0 {
            x := 1
            for j:=1;j<i+1;j++{
                x*=j
            }
            ret = append(ret, x)
        }else {
            x := 0
            for j:=1;j<i+1;j++{
                x+=j
            }
            ret = append(ret, x)
        }
    }
    return ret
}

