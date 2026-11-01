// Jingles for the end of the long steps (extract sound, build); the files live in `public/`.
export function playResult(success: boolean) {
  const audio = new Audio(success ? "/success.mp3" : "/failure.mp3");
  audio.play().catch(() => {});
}
