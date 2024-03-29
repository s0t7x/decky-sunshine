import { useState, useEffect, SetStateAction, Dispatch } from 'react';

export const playSound = (sound: string) => {
  const audio = new Audio(sound);
  audio.play();
}

//Function to use storage, and automatically store it in local storage
export function useLocalStorageState <S>(key: string, defaultValue: S | (() => S)): [S, Dispatch<SetStateAction<S>>] {
  const [state, setState] = useState(() => {
    const valueInLocalStorage = localStorage.getItem(key);
    if (valueInLocalStorage) {
      try
      {
        let value = JSON.parse(valueInLocalStorage);
        console.log(key, valueInLocalStorage);
        return value;
      }
      catch(ex)
      {
        return null;
      }
    }

    return typeof defaultValue === 'function' ? (defaultValue as Function)() : defaultValue;
  });

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify(state));
  }, [key, state]);

  return [state, setState];
}