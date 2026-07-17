
// Given a non-empty list of integers, return the sum of all of the odd elements that are in even positions.
// 
// Examples
// Solution([5, 8, 7, 1]) ==> 12
// Solution([3, 3, 3, 3, 3]) ==> 9
// Solution([30, 13, 24, 321]) ==>0
func Solution(lst []int) int {
    sum:=0
    for i, x := range lst {
        if i&1==0&&x&1==1 {
            sum+=x
        }
    }
    return sum
}

