import React from "react";
import { StyleSheet, TouchableOpacity } from "react-native";
import { useNavigation } from "@react-navigation/native";
import { BotMessageSquare } from "lucide-react-native";

interface Props {
  bottom?: number;
  right?: number;
  onPress: () => void;
}

export default function WC01DChatbotFloating({
  bottom = 104,
  right = 24,
  onPress,
}: Props) {
  return (
    <TouchableOpacity
      style={[
        styles.floating_button,
        {
          bottom,
          right,
        },
      ]}
      onPress={onPress}
      activeOpacity={0.8}
    >
      <BotMessageSquare size={24} color="#FFFFFF" />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  floating_button: {
    position: "absolute",
    width: 55,
    height: 55,
    borderRadius: 100,
    backgroundColor: "#111FA2",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 16,

    shadowColor: "#111FA2",
    shadowOffset: {
      width: 0,
      height: 0,
    },
    shadowOpacity: 0.25,
    shadowRadius: 10,
    elevation: 8,
  },
});
