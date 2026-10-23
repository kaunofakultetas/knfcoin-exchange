// -----------------------------------------------------------
//  [*] Tests — CopyableAddress (an address with a copy button)
//
//  The address in full beside its "Copy" button; a click puts
//  exactly the address on the clipboard and flips the button
//  to "Copied ✓" for a second and a half. A clipboard the
//  browser refuses (an insecure context, a denied permission)
//  leaves the button as it was, and the button never submits
//  a form it sits in.
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { act, fireEvent, screen } from '@testing-library/react'
import { renderPage } from '../support/render'
import { settle } from '../support/backend/contract'
import * as f from '../support/backend/fixtures'
import CopyableAddress from '@/pages/Exchange/components/CopyableAddress.jsx'


const ADDRESS = f.RESERVE_LTC

// "Copy" or "Copied ✓", whichever it says now
const copyButton = () => screen.getByRole('button', { name: /^Cop/ })







// -----------------------------------------------------------
// Copying
// -----------------------------------------------------------
//
// The address shown in full beside its button: a click copies
// exactly the address and says so for a moment, and a
// clipboard the browser refuses breaks nothing.
// -----------------------------------------------------------

describe('CopyableAddress', () => {

  it('shows the address in full, beside a "Copy" button', () => {
    renderPage(<CopyableAddress value={ADDRESS} />)
    expect(screen.getByText(ADDRESS)).toBeInTheDocument()
    expect(copyButton()).toHaveTextContent(/^Copy$/)
  })


  it('"Copy" puts exactly the address on the clipboard and says "Copied ✓"', async () => {
    const { user } = renderPage(<CopyableAddress value={ADDRESS} />)
    const write = vi.spyOn(navigator.clipboard, 'writeText')

    await user.click(copyButton())

    expect(write).toHaveBeenCalledExactlyOnceWith(ADDRESS)
    expect(await navigator.clipboard.readText()).toBe(ADDRESS)
    expect(copyButton()).toHaveTextContent(/^Copied ✓$/)
  })


  it('says "Copy" again a second and a half later', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    renderPage(<CopyableAddress value={ADDRESS} />)
    vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()

    await act(async () => { fireEvent.click(copyButton()) })
    expect(copyButton()).toHaveTextContent(/^Copied ✓$/)

    act(() => { vi.advanceTimersByTime(1499) })
    expect(copyButton()).toHaveTextContent(/^Copied ✓$/)
    act(() => { vi.advanceTimersByTime(1) })
    expect(copyButton()).toHaveTextContent(/^Copy$/)
  })


  it('a clipboard the browser refuses leaves "Copy" as it was — nothing breaks', async () => {
    const { user } = renderPage(<CopyableAddress value={ADDRESS} />)
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new DOMException('Write permission denied.', 'NotAllowedError'))

    await user.click(copyButton())
    await settle()

    expect(copyButton()).toHaveTextContent(/^Copy$/)
    expect(screen.getByText(ADDRESS)).toBeInTheDocument()
  })


  it('never submits a form it sits in', async () => {
    const submitted = vi.fn((event) => event.preventDefault())
    const { user } = renderPage(<form onSubmit={submitted}><CopyableAddress value={ADDRESS} /></form>)

    await user.click(copyButton())

    expect(submitted).not.toHaveBeenCalled()
    expect(copyButton()).toHaveAttribute('type', 'button')
  })
})
