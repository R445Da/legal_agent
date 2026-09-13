import { cva, type VariantProps } from 'class-variance-authority'
import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

const button = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap font-medium transition-[background,color,border,transform,box-shadow] duration-150 active:scale-[.97] disabled:opacity-40 disabled:active:scale-100 select-none',
  {
    variants: {
      variant: {
        primary: 'bg-white text-ink-900 hover:bg-white/90 shadow-[0_8px_24px_rgba(255,255,255,.08)]',
        secondary: 'border border-white/10 bg-white/[.045] text-white/85 hover:bg-white/[.08] hover:text-white',
        ghost: 'text-white/55 hover:text-white hover:bg-white/[.05]',
        approve: 'bg-emerald-300 text-emerald-950 hover:bg-emerald-200 shadow-[0_8px_30px_rgba(110,231,183,.18)]',
        danger: 'border border-rose-300/20 bg-rose-400/10 text-rose-100 hover:bg-rose-400/15',
        suggest: 'border border-dashed border-violet-300/40 bg-violet-400/[.08] text-violet-100 hover:bg-violet-400/[.14]',
      },
      size: {
        sm: 'h-8 px-3 text-xs rounded-xl',
        md: 'h-10 px-4 text-[13px] rounded-2xl',
        lg: 'h-11 px-5 text-sm rounded-2xl',
        icon: 'h-10 w-10 rounded-2xl text-sm',
        'icon-sm': 'h-8 w-8 rounded-xl text-xs',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
)

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof button> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, type = 'button', ...props }, ref) => (
  <button ref={ref} type={type} className={cn(button({ variant, size }), className)} {...props} />
))
Button.displayName = 'Button'
