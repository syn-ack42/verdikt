import { useEffect, useState } from 'react'

export function useIsMobile(breakpoint = 640) {
  const [v, setV] = useState(() => window.innerWidth < breakpoint)
  useEffect(() => {
    const fn = () => setV(window.innerWidth < breakpoint)
    window.addEventListener('resize', fn)
    return () => window.removeEventListener('resize', fn)
  }, [breakpoint])
  return v
}
