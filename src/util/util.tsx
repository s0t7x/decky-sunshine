export const playSound = (sound: string) => {
  const audio = new Audio(sound);
  audio.play();
}